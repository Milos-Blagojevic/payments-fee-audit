"""Reference fee engine: hand-computed examples per term kind, plus an end-to-end run on raw VARCHAR tables."""

import datetime as dt
from fractions import Fraction

import duckdb
import pytest

from feeaudit.reference import DEFAULT_CONTRACTS, DEFAULT_INTERCHANGE, run, terms
from feeaudit.reference.contracts import load_interchange, load_provider_contracts
from feeaudit.reference.engine import Payment, compute_expected_charges, parse_ts

CONTRACTS = load_provider_contracts(DEFAULT_CONTRACTS)
INTERCHANGE = load_interchange(DEFAULT_INTERCHANGE)
NG_V1, NG_V2 = CONTRACTS["northgate"].versions
BP_V1 = CONTRACTS["brightpay"].versions[0]
KP_V1, KP_V2 = CONTRACTS["kestrel"].versions


def term(cv, kind, **match):
    (found,) = [t for t in cv.terms_of(kind) if all(t[k] == v for k, v in match.items())]
    return found


# --- rounding ----------------------------------------------------------------


@pytest.mark.parametrize(
    "value, half_up, half_even",
    [
        (Fraction(5, 2), 3, 2),  # 2.5: tie, even neighbour is 2
        (Fraction(7, 2), 4, 4),  # 3.5: tie, even neighbour is 4
        (Fraction(-5, 2), -3, -2),  # ties away from zero vs to even
        (Fraction(249, 100), 2, 2),  # 2.49: not a tie
        (Fraction(251, 100), 3, 3),
        (Fraction(4), 4, 4),
    ],
)
def test_round_minor_modes(value, half_up, half_even):
    assert terms.round_minor(value, "half_up") == half_up
    assert terms.round_minor(value, "half_even") == half_even


def test_round_minor_rejects_unknown_mode():
    with pytest.raises(ValueError):
        terms.round_minor(Fraction(1, 2), "bankers")


def test_blended_rate_tie_half_even_vs_half_up():
    segments = term(BP_V1, "blended_rate")["segments"]
    # 1750 × 140 / 10000 = 24.5 → half_even 24 (+25 fixed = 49), half_up 25 (+25 = 50)
    assert terms.blended_rate(1750, "succeeded", "eea_consumer", segments, "no_fee", "half_even") == 49
    assert terms.blended_rate(1750, "succeeded", "eea_consumer", segments, "no_fee", "half_up") == 50
    # 1250 × 140 / 10000 = 17.5 → both modes 18 (18 is even)
    assert terms.blended_rate(1250, "succeeded", "eea_consumer", segments, "no_fee", "half_even") == 43
    assert terms.blended_rate(1250, "succeeded", "eea_consumer", segments, "no_fee", "half_up") == 43


def test_blended_rate_segments_and_failed_attempts():
    segments = term(BP_V1, "blended_rate")["segments"]
    # other: 10000 × 290 / 10000 = 290, + 25
    assert terms.blended_rate(10_000, "succeeded", "other", segments, "no_fee", "half_even") == 315
    assert terms.blended_rate(10_000, "declined", "other", segments, "no_fee", "half_even") == 0
    assert terms.blended_rate(10_000, "failed", "eea_consumer", segments, "no_fee", "half_even") == 0
    with pytest.raises(ValueError):
        terms.blended_rate(10_000, "pending", "other", segments, "no_fee", "half_even")


@pytest.mark.parametrize(
    "card_type, region, segment",
    [
        ("consumer_debit", "domestic", "eea_consumer"),
        ("consumer_credit", "intra_eea", "eea_consumer"),
        ("consumer_credit", "inter_regional", "other"),
        ("commercial", "domestic", "other"),
    ],
)
def test_card_segment(card_type, region, segment):
    assert terms.card_segment(card_type, region) == segment


# --- tiers -------------------------------------------------------------------


@pytest.mark.parametrize(
    "volume, v1_bps, v2_bps",
    [
        (249_999_999, 45, 45),  # just below the first bound
        (250_000_000, 35, 32),  # at the bound: up_to is exclusive, so tier 2
        (250_000_001, 35, 32),
        (799_999_999, 35, 32),
        (800_000_000, 28, 28),  # at the second bound: tier 3
        (800_000_001, 28, 28),
    ],
)
def test_retroactive_markup_tier_thresholds(volume, v1_bps, v2_bps):
    v1_tiers = term(NG_V1, "markup_bps_tiered")["tiers"]
    v2_tiers = term(NG_V2, "markup_bps_tiered")["tiers"]
    assert terms.tier_bps(volume, v1_tiers) == v1_bps
    assert terms.tier_bps(volume, v2_tiers) == v2_bps
    # Retroactive: the payment's markup uses the month's tier, 10000 × bps / 10000 = bps.
    assert terms.markup_retroactive(10_000, volume, v1_tiers, "half_up") == v1_bps


def test_markup_rounds_per_payment():
    tiers = term(NG_V1, "markup_bps_tiered")["tiers"]
    # 12345 × 45 / 10000 = 55.5525 → 56
    assert terms.markup_retroactive(12_345, 1_000, tiers, "half_up") == 56
    # 10 × 45 / 10000 = 0.045 → 0
    assert terms.markup_retroactive(10, 1_000, tiers, "half_up") == 0


@pytest.mark.parametrize(
    "volume, half_even, half_up",
    [
        (149_999_999, 0, 0),  # below the 150,000,000 threshold
        (150_000_000, 0, 0),  # at it: V does not exceed the threshold
        (150_000_001, 0, 0),  # 1 × 15 / 10000 = 0.0015 → 0
        (150_001_000, -2, -2),  # 1000 × 15 / 10000 = 1.5 → 2 both ways
        (150_003_000, -4, -5),  # 3000 × 15 / 10000 = 4.5 → 4 half_even, 5 half_up
        (150_010_000, -15, -15),  # 10000 × 15 / 10000 = 15
        (200_000_000, -75_000, -75_000),  # 50,000,000 × 15 / 10000
    ],
)
def test_marginal_volume_adjustment(volume, half_even, half_up):
    tiers = term(BP_V1, "volume_discount")["tiers"]  # 140 bps up to 150,000,000, then 125 bps
    assert terms.volume_adjustment(volume, tiers, "half_even") == half_even
    assert terms.volume_adjustment(volume, tiers, "half_up") == half_up


# --- pass-through, fixed, refund, chargeback, minimum ------------------------------


def test_pass_through():
    # visa consumer_debit domestic: 20 bps interchange, 2 bps + 1 scheme
    rates = INTERCHANGE["interchange_table_v1", "visa", "consumer_debit", "domestic"]
    # 10000 × 20 / 10000 = 20; 10000 × 2 / 10000 + 1 = 3
    assert terms.pass_through(10_000, *rates, "half_up") == (20, 3)
    # 250 × 20 / 10000 = 0.5 → 1 (half_up); 250 × 2 / 10000 = 0.05 → 0, + 1
    assert terms.pass_through(250, *rates, "half_up") == (1, 1)
    assert terms.pass_through(250, *rates, "half_even") == (0, 1)


def test_fixed_and_chargeback_fees():
    assert terms.per_transaction_fixed(term(NG_V2, "per_transaction_fixed")["amount_minor"]) == 4
    assert terms.chargeback_fee(term(NG_V1, "chargeback_fee")["amount_minor"]) == 1500
    assert terms.chargeback_fee(term(BP_V1, "chargeback_fee")["amount_minor"]) == 2000


def test_refund_credit():
    ng = term(NG_V2, "refund")
    bp = term(BP_V1, "refund")
    # Northgate: fee 10, credit of minus the original's expected markup
    assert terms.refund(ng["fee_minor"], ng["credit_original_markup"], 56) == (10, -56)
    # Brightpay: fee 20, no credit
    assert terms.refund(bp["fee_minor"], bp["credit_original_markup"], 56) == (20, None)


@pytest.mark.parametrize(
    "markup, top_up",
    [(0, 250_000), (249_999, 1), (250_000, 0), (250_001, 0)],
)
def test_monthly_minimum(markup, top_up):
    assert terms.monthly_minimum(term(NG_V1, "monthly_minimum")["amount_minor"], markup) == top_up


# --- payouts and FX ------------------------------------------------------------


@pytest.mark.parametrize(
    "amount_usd, fee",
    [
        (900_000, 800),  # E = 900000 / 1.25 = 720000; 720 → minimum 800
        (1_000_000, 800),  # E = 800000; 800 = minimum
        (1_001_250, 801),  # E = 801000; 801, just above the minimum
        (4_998_750, 3_999),  # E = 3999000; 3999, just below the cap
        (5_000_000, 4_000),  # E = 4000000; 4000 = cap
        (5_001_250, 4_000),  # E = 4001000; 4001 → cap 4000
    ],
)
def test_swift_payout_fee_min_and_cap(amount_usd, fee):
    swift = term(KP_V1, "payout_fee", rail="swift")  # 10 bps, min 800, cap 4000
    assert terms.payout_fee(amount_usd, Fraction("1.250000"), swift, "half_up") == fee


def test_swift_eur_equivalent_rounds_before_bps():
    swift = term(KP_V1, "payout_fee", rail="swift")
    # E = 1,000,001 / 1.25 = 800000.8 → 800001; 800001 × 10 / 10000 = 800.001 → 800
    assert terms.eur_equivalent(1_000_001, Fraction("1.25"), "half_up") == 800_001
    assert terms.payout_fee(1_000_001, Fraction("1.25"), swift, "half_up") == 800


def test_fixed_payout_fees():
    assert terms.payout_fee(123_456, Fraction(1), term(KP_V1, "payout_fee", rail="sepa"), "half_up") == 20
    assert terms.payout_fee(123_456, Fraction("0.85"), term(KP_V1, "payout_fee", rail="faster_payments"), "half_up") == 30
    assert terms.payout_fee(123_456, Fraction("4.3"), term(KP_V2, "payout_fee", rail="elixir"), "half_up") == 30
    assert not [t for t in KP_V1.terms_of("payout_fee") if t["rail"] == "elixir"]


def _spread_bps(amount_minor, eur_debit_minor, mid):
    """Realised spread of a EUR debit against mid: (1 − (amount / debit) / mid) × 10000."""
    return (1 - Fraction(amount_minor, eur_debit_minor) / mid) * 10_000


def test_fx_allowance_at_cap_and_one_unit_over():
    caps = term(KP_V1, "fx_spread_cap")["caps_bps"]
    mid = Fraction("0.800000")
    # GBP cap 40 bps: 79680 / (0.8 × 0.996) = 79680 / 0.7968 = 100000 exactly
    allowance = terms.fx_spread_cap(79_680, mid, caps["GBP"], "half_up")
    assert allowance == 100_000
    assert _spread_bps(79_680, allowance, mid) == 40  # a debit at the allowance is exactly at the cap
    assert _spread_bps(79_680, allowance + 1, mid) > 40  # one minor unit more is over it
    # PLN cap 90 bps: 396400 / (4 × 0.991) = 396400 / 3.964 = 100000
    assert terms.fx_spread_cap(396_400, Fraction("4.000000"), caps["PLN"], "half_up") == 100_000
    # 100 / (1.25 × 0.996) = 100 / 1.245 = 80.32... → 80
    assert terms.fx_spread_cap(100, Fraction("1.25"), caps["USD"], "half_up") == 80


# --- contract versions and months ------------------------------------------------


@pytest.mark.parametrize(
    "provider, ts, version, month",
    [
        ("northgate", "2026-03-31T21:59:59Z", 1, dt.date(2026, 3, 1)),  # 23:59:59 in Berlin (CEST)
        ("northgate", "2026-03-31T22:30:00Z", 2, dt.date(2026, 4, 1)),  # 00:30 on 1 April in Berlin
        ("northgate", "2026-02-28T23:30:00Z", 1, dt.date(2026, 3, 1)),  # 00:30 on 1 March in Berlin (CET)
        ("kestrel", "2026-03-31T23:59:59Z", 1, dt.date(2026, 3, 1)),  # UTC contract
        ("kestrel", "2026-04-01T00:00:00Z", 2, dt.date(2026, 4, 1)),
        ("brightpay", "2026-03-31T22:30:00Z", 1, dt.date(2026, 3, 1)),
    ],
)
def test_contract_version_and_month_in_contract_timezone(provider, ts, version, month):
    contract = CONTRACTS[provider]
    assert contract.version_at(parse_ts(ts)).version == version
    assert contract.month_of(parse_ts(ts)) == month


def test_event_before_first_version_is_an_error():
    with pytest.raises(ValueError):
        CONTRACTS["northgate"].version_at(parse_ts("2025-06-30T12:00:00Z"))


def test_parse_ts_requires_utc_z():
    assert parse_ts("2026-03-31T22:30:00Z") == dt.datetime(2026, 3, 31, 22, 30, tzinfo=dt.UTC)
    with pytest.raises(ValueError):
        parse_ts("2026-03-31T22:30:00")


def test_declined_attempts_rows_and_volume():
    def pay(pid, provider, status, amount):
        return Payment(pid, parse_ts("2026-05-10T10:00:00Z"), amount, "EUR", "visa", "consumer_debit", "domestic", status, provider)

    rows = compute_expected_charges(
        CONTRACTS,
        INTERCHANGE,
        [
            pay("ng-ok", "northgate", "succeeded", 10_000),
            pay("ng-declined", "northgate", "declined", 300_000_000),
            pay("bp-failed", "brightpay", "failed", 200_000_000),
        ],
        [],
        [],
        [],
        {},
    )
    by_event = {}
    for r in rows:
        by_event.setdefault(r.event_id, {})[r.component] = r.expected_minor
    assert "ng-declined" not in by_event  # no rows at Northgate
    assert by_event["bp-failed"] == {"transaction_fee": 0}
    # The declined 300M does not count towards the tier: 10000 × 45 / 10000 = 45
    assert by_event["ng-ok"]["markup"] == 45
    # The failed 200M does not count towards the Brightpay segment volume
    assert by_event[None] == {"monthly_minimum": 250_000 - 45, "volume_adjustment": 0}


# --- end to end on raw VARCHAR tables -------------------------------------------------

RAW_TABLES = {
    "ledger__payments": (
        ["payment_id", "client_id", "created_at", "amount_minor", "currency", "card_scheme", "card_type", "card_region", "status", "provider"],
        [
            ["ng-p1", "c1", "2026-03-31T22:30:00Z", "100000", "EUR", "visa", "consumer_debit", "domestic", "succeeded", "northgate"],
            ["ng-p2", "c1", "2026-04-10T10:00:00Z", "249900000", "EUR", "visa", "consumer_debit", "domestic", "succeeded", "northgate"],
            ["ng-p3", "c2", "2026-04-11T10:00:00Z", "5000", "EUR", "visa", "consumer_debit", "domestic", "declined", "northgate"],
            ["ng-p4", "c2", "2026-03-15T12:00:00Z", "20000", "EUR", "mastercard", "commercial", "inter_regional", "succeeded", "northgate"],
            ["bp-p1", "c3", "2026-03-31T22:30:00Z", "1750", "EUR", "visa", "consumer_credit", "intra_eea", "succeeded", "brightpay"],
            ["bp-p2", "c3", "2026-03-10T00:00:00Z", "9999", "EUR", "visa", "consumer_credit", "intra_eea", "declined", "brightpay"],
            ["bp-p3", "c3", "2026-03-11T00:00:00Z", "150010000", "EUR", "mastercard", "consumer_debit", "domestic", "succeeded", "brightpay"],
            ["bp-p4", "c4", "2026-03-12T00:00:00Z", "10000", "EUR", "visa", "commercial", "domestic", "succeeded", "brightpay"],
        ],
    ),
    "ledger__refunds": (
        ["refund_id", "payment_id", "created_at", "amount_minor", "currency"],
        [
            ["ng-r1", "ng-p4", "2026-04-02T08:00:00Z", "20000", "EUR"],
            ["bp-r1", "bp-p4", "2026-03-13T00:00:00Z", "10000", "EUR"],
        ],
    ),
    "ledger__chargebacks": (
        ["chargeback_id", "payment_id", "created_at", "amount_minor", "currency"],
        [
            ["ng-c1", "ng-p1", "2026-04-20T00:00:00Z", "100000", "EUR"],
            ["bp-c1", "bp-p1", "2026-04-02T00:00:00Z", "1750", "EUR"],
        ],
    ),
    "ledger__payouts": (
        ["payout_id", "client_id", "created_at", "executed_at", "amount_minor", "currency", "rail", "provider"],
        [
            ["kp-1", "c1", "2026-03-30T10:00:00Z", "2026-03-31T23:30:00Z", "50000", "EUR", "sepa", "kestrel"],
            ["kp-2", "c2", "2026-04-03T08:00:00Z", "2026-04-03T09:10:00Z", "396400", "PLN", "elixir", "kestrel"],
            ["kp-3", "c3", "2026-03-05T12:00:00Z", "2026-03-05T14:45:00Z", "4980000", "USD", "swift", "kestrel"],
            ["kp-4", "c4", "2026-03-05T12:00:00Z", "2026-03-05T14:00:00Z", "79680", "GBP", "faster_payments", "kestrel"],
        ],
    ),
    "fx__mid_hourly": (
        ["pair", "hour_start_utc", "mid"],
        [
            ["EURPLN", "2026-04-03T09:00:00Z", "4.000000"],
            ["EURPLN", "2026-04-03T10:00:00Z", "4.100000"],
            ["EURUSD", "2026-03-05T13:00:00Z", "1.300000"],
            ["EURUSD", "2026-03-05T14:00:00Z", "1.250000"],
            ["EURGBP", "2026-03-05T14:00:00Z", "0.800000"],
        ],
    ),
}

NG, BP, KP = "NG-2025-01", "BP-2025-07", "KP-2025-09"
MAR, APR = dt.date(2026, 3, 1), dt.date(2026, 4, 1)

EXPECTED = {
    # ng-p1: 00:30 on 1 April in Berlin → v2, April. April volume 100,000 + 249,900,000 = 250,000,000
    # (succeeded only; ng-p3 is declined) → at the first bound, so tier 2 at 32 bps (v2).
    ("payment", "ng-p1", "northgate", APR, "interchange", NG, 2, "3.1", 200),  # 100000 × 20 / 1e4
    ("payment", "ng-p1", "northgate", APR, "scheme_fee", NG, 2, "3.1", 21),  # 100000 × 2 / 1e4 + 1
    ("payment", "ng-p1", "northgate", APR, "markup", NG, 2, "4.2", 320),  # 100000 × 32 / 1e4
    ("payment", "ng-p1", "northgate", APR, "fixed_fee", NG, 2, "4.3", 4),
    ("payment", "ng-p2", "northgate", APR, "interchange", NG, 2, "3.1", 499_800),  # 249.9M × 20 / 1e4
    ("payment", "ng-p2", "northgate", APR, "scheme_fee", NG, 2, "3.1", 49_981),  # 249.9M × 2 / 1e4 + 1
    ("payment", "ng-p2", "northgate", APR, "markup", NG, 2, "4.2", 799_680),  # 249.9M × 32 / 1e4
    ("payment", "ng-p2", "northgate", APR, "fixed_fee", NG, 2, "4.3", 4),
    # ng-p4: March, v1, March volume 20,000 → 45 bps. mastercard commercial inter_regional: 200 bps, 15 bps + 2
    ("payment", "ng-p4", "northgate", MAR, "interchange", NG, 1, "3.1", 400),  # 20000 × 200 / 1e4
    ("payment", "ng-p4", "northgate", MAR, "scheme_fee", NG, 1, "3.1", 32),  # 20000 × 15 / 1e4 + 2
    ("payment", "ng-p4", "northgate", MAR, "markup", NG, 1, "4.2", 90),  # 20000 × 45 / 1e4
    ("payment", "ng-p4", "northgate", MAR, "fixed_fee", NG, 1, "4.3", 4),
    # ng-r1 (April, v2) refunds ng-p4: credit is ng-p4's own expected markup (March tier, v1)
    ("refund", "ng-r1", "northgate", APR, "refund_fee", NG, 2, "5.1", 10),
    ("refund", "ng-r1", "northgate", APR, "markup_credit", NG, 2, "5.1", -90),
    ("chargeback", "ng-c1", "northgate", APR, "chargeback_fee", NG, 2, "6.1", 1500),
    # Minimum 250,000: March markup 90 → 249,910; April markup 320 + 799,680 = 800,000 → 0
    ("provider_month", None, "northgate", MAR, "monthly_minimum", NG, 1, "7.4", 249_910),
    ("provider_month", None, "northgate", APR, "monthly_minimum", NG, 2, "7.4", 0),
    # Brightpay (UTC, half_even): bp-p1 at 22:30Z on 31 March is March
    ("payment", "bp-p1", "brightpay", MAR, "transaction_fee", BP, 1, "3.1", 49),  # 1750 × 140 / 1e4 = 24.5 → 24, + 25
    ("payment", "bp-p2", "brightpay", MAR, "transaction_fee", BP, 1, "3.1", 0),  # declined
    ("payment", "bp-p3", "brightpay", MAR, "transaction_fee", BP, 1, "3.1", 2_100_165),  # 150.01M × 140 / 1e4 + 25
    ("payment", "bp-p4", "brightpay", MAR, "transaction_fee", BP, 1, "3.1", 315),  # 10000 × 290 / 1e4 + 25
    ("refund", "bp-r1", "brightpay", MAR, "refund_fee", BP, 1, "5.2", 20),
    ("chargeback", "bp-c1", "brightpay", APR, "chargeback_fee", BP, 1, "6.3", 2000),
    # March EEA consumer volume 1,750 + 150,010,000 = 150,011,750; excess 11,750 × 15 / 1e4 = 17.625 → −18
    ("provider_month", None, "brightpay", MAR, "volume_adjustment", BP, 1, "3.4", -18),
    ("provider_month", None, "brightpay", APR, "volume_adjustment", BP, 1, "3.4", 0),  # only a chargeback in April
    # Kestrel (UTC, half_up), version and month by executed_at, mid at the execution hour
    ("payout", "kp-1", "kestrel", MAR, "payout_fee", KP, 1, "2.1", 20),  # SEPA, no FX row
    ("payout", "kp-2", "kestrel", APR, "payout_fee", KP, 2, "2.4", 30),  # Elixir exists from v2
    ("payout", "kp-2", "kestrel", APR, "fx_conversion", KP, 2, "4.1", 100_000),  # 396400 / (4 × 0.991)
    # kp-3: mid 1.25 at 14:00 (not 1.30 at 13:00); E = 4980000 / 1.25 = 3984000; × 10 / 1e4 = 3984
    ("payout", "kp-3", "kestrel", MAR, "payout_fee", KP, 1, "2.3", 3_984),
    ("payout", "kp-3", "kestrel", MAR, "fx_conversion", KP, 1, "4.1", 4_000_000),  # 4980000 / (1.25 × 0.996)
    ("payout", "kp-4", "kestrel", MAR, "payout_fee", KP, 1, "2.2", 30),
    ("payout", "kp-4", "kestrel", MAR, "fx_conversion", KP, 1, "4.1", 100_000),  # 79680 / (0.8 × 0.996)
}


def _raw_db() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("create schema raw")
    for table, (columns, rows) in RAW_TABLES.items():
        all_columns = [*columns, "source_file", "source_row"]
        con.execute(f"create table raw.{table} ({', '.join(f'{c} varchar' for c in all_columns)})")
        con.executemany(
            f"insert into raw.{table} values ({', '.join('?' for _ in all_columns)})",
            [[*row, f"data/raw/{table}.csv", str(i)] for i, row in enumerate(rows, start=1)],
        )
    return con


def test_end_to_end_on_raw_varchar_tables():
    con = _raw_db()
    rows = run(con)
    assert len(rows) == len(EXPECTED)
    table = con.execute(
        "select event_type, event_id, provider, month, component, contract_id, contract_version, clause,"
        " expected_minor, currency from reference.expected_charges"
    ).fetchall()
    assert {r[:-1] for r in table} == EXPECTED
    assert {r[-1] for r in table} == {"EUR"}
    assert len(table) == len(EXPECTED)
    schema = dict(con.execute("select column_name, data_type from information_schema.columns"
                              " where table_schema = 'reference' and table_name = 'expected_charges'").fetchall())
    assert schema == {
        "event_type": "VARCHAR",
        "event_id": "VARCHAR",
        "provider": "VARCHAR",
        "month": "DATE",
        "component": "VARCHAR",
        "contract_id": "VARCHAR",
        "contract_version": "INTEGER",
        "clause": "VARCHAR",
        "expected_minor": "BIGINT",
        "currency": "VARCHAR",
    }
    # A second run replaces the table instead of appending.
    run(con)
    assert con.execute("select count(*) from reference.expected_charges").fetchone()[0] == len(EXPECTED)


def test_missing_execution_hour_mid_is_an_error():
    con = _raw_db()
    con.execute("delete from raw.fx__mid_hourly where pair = 'EURGBP'")
    with pytest.raises(ValueError, match="no mid for EURGBP"):
        run(con)


def test_rail_without_a_fee_in_the_version_is_an_error():
    con = _raw_db()
    # Elixir is only in version 2; a March execution falls under version 1.
    con.execute("update raw.ledger__payouts set executed_at = '2026-03-03T09:10:00Z' where payout_id = 'kp-2'")
    con.execute("insert into raw.fx__mid_hourly values ('EURPLN', '2026-03-03T09:00:00Z', '4.000000', 'x', '9')")
    with pytest.raises(ValueError, match="rail 'elixir'"):
        run(con)
