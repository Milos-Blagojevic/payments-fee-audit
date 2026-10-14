"""The ledger: card payments, refunds, chargebacks, payouts, and the hourly FX mid series."""

import numpy as np

from generator.common import CURRENCIES, RAILS, SUCCEEDED, choice_shares, day_ts, stream

PAIRS = ["EURGBP", "EURUSD", "EURCHF", "EURPLN"]


def period(cfg):
    """(start, end) UTC timestamps; end is exclusive."""
    p = cfg["period"]
    return day_ts(p["start"]), day_ts(p["end"]) + 86400


def watermark(cfg):
    """Events created at or after this timestamp are not in the ledger yet (N07)."""
    return period(cfg)[1] - 86400 * cfg["ledger_lag_days"]


def build_fx(cfg):
    """Hourly mid per pair as integer micro-units (6 decimals): {'hour0': first hour index, 'mid': [4, n]}."""
    rng = stream(cfg, "fx")
    start, end = period(cfg)
    f = cfg["fx"]
    hour0 = start // 3600 - 24 * f["days_before"]
    n = (end // 3600 + 24 * f["days_after"]) - hour0
    mids = []
    for pair in PAIRS:
        spec = f["pairs"][pair]
        steps = rng.normal(0.0, spec["daily_vol"] / np.sqrt(24), n)
        steps[0] = 0.0
        mids.append(np.rint(spec["start"] * np.exp(np.cumsum(steps)) * 1_000_000).astype(np.int64))
    return {"hour0": hour0, "mid": np.vstack(mids)}


def mid_at(fx, currency, ts):
    """Mid (micro-units) for currency codes (index into CURRENCIES, not EUR) at the hour containing ts."""
    return fx["mid"][np.asarray(currency) - 1, np.asarray(ts) // 3600 - fx["hour0"]]


def _draw_days(rng, cfg, n, month_weights, weekday_weights):
    start, end = period(cfg)
    days = np.arange(start, end, 86400)
    d64 = days.astype("datetime64[s]")
    month = d64.astype("datetime64[M]").astype(np.int64) % 12 + 1
    weekday = (d64.astype("datetime64[D]").astype(np.int64) + 3) % 7
    w = np.array([month_weights.get(int(m), 1.0) for m in month]) * np.asarray(weekday_weights)[weekday]
    return days[rng.choice(len(days), size=n, p=w / w.sum())]


def build_payments(cfg, world):
    """All card payment attempts (sorted by time), including the phantom candidates."""
    rng = stream(cfg, "payments")
    p = cfg["payments"]
    n = p["attempts"]
    day = _draw_days(rng, cfg, n, p["month_weights"], p["weekday_weights"])
    hw = np.asarray(p["hour_weights"], dtype=float)
    ts = day + rng.choice(24, size=n, p=hw / hw.sum()) * 3600 + rng.integers(0, 3600, n)
    client = rng.choice(len(world["weight"]), size=n, p=world["weight"])
    status = choice_shares(rng, p["status_shares"], n)

    eur = world["ticket_median_eur"][client] * np.exp(rng.normal(0.0, p["amount_sigma"], n))
    eur = np.clip(eur, p["amount_min_eur"], p["amount_max_eur"])
    cents = np.rint(eur * 100).astype(np.int64)
    pp = p["price_points"]
    u = rng.random(n)
    whole = u < pp["whole"]
    half = (u >= pp["whole"]) & (u < pp["whole"] + pp["half"])
    nn = (u >= pp["whole"] + pp["half"]) & (u < pp["whole"] + pp["half"] + pp["ninety_nine"])
    cents = np.where(whole, np.maximum(100, np.rint(cents / 100) * 100), cents)
    cents = np.where(half, np.maximum(100, np.rint(cents / 50) * 50), cents)
    cents = np.where(nn, np.maximum(99, cents // 100 * 100 - 1), cents).astype(np.int64)

    scheme = choice_shares(rng, p["card_scheme"], n)
    card_type = choice_shares(rng, p["card_type"], n)
    region = choice_shares(rng, p["card_region"], n)

    order = np.lexsort((rng.random(n), ts))
    ts, client, status, cents = ts[order], client[order], status[order], cents[order]
    scheme, card_type, region = scheme[order], card_type[order], region[order]
    switched = (world["switch_ts"][client] >= 0) & (ts >= world["switch_ts"][client])
    provider = np.where(switched, world["provider_after"][client], world["provider"][client])
    return {
        "id": np.array([f"pay_{i:07d}" for i in range(1, n + 1)], dtype=object),
        "ts": ts,
        "client": client,
        "amount": cents,
        "scheme": scheme,
        "card_type": card_type,
        "region": region,
        "status": status,
        "provider": provider,
    }


def _follow_ups(rng, cfg, payments, eligible, spec, prefix):
    """Events that follow a payment after a random delay (full amount); dropped after the period end."""
    _, end = period(cfg)
    pick = np.flatnonzero(eligible & (rng.random(len(eligible)) < spec["rate"]))
    delay = rng.integers(spec["min_days"] * 86400, spec["max_days"] * 86400 + 1, len(pick))
    ts = payments["ts"][pick] + delay
    keep = ts < end
    pick, ts = pick[keep], ts[keep]
    order = np.argsort(ts, kind="stable")
    pick, ts = pick[order], ts[order]
    return {
        "id": np.array([f"{prefix}_{i:06d}" for i in range(1, len(pick) + 1)], dtype=object),
        "payment": pick,
        "ts": ts,
        "amount": payments["amount"][pick],
    }, pick


def build_refunds_chargebacks(cfg, payments):
    rng = stream(cfg, "refunds")
    ok = payments["status"] == SUCCEEDED
    refunds, _ = _follow_ups(rng, cfg, payments, ok, cfg["refunds"], "ref")
    refunded = np.zeros(len(ok), dtype=bool)
    refunded[refunds["payment"]] = True
    chargebacks, _ = _follow_ups(rng, cfg, payments, ok & ~refunded, cfg["chargebacks"], "cb")
    return refunds, chargebacks


def build_payouts(cfg, world, fx):
    rng = stream(cfg, "payouts")
    po = cfg["payouts"]
    n = po["count"]
    day = _draw_days(rng, cfg, n, {}, po["weekday_weights"])
    h0, h1 = po["hours_utc"]
    ts = day + rng.integers(h0 * 3600, h1 * 3600, n)
    client = rng.choice(len(world["weight"]), size=n, p=world["weight"])
    currency = np.zeros(n, dtype=np.int64)
    for c in range(len(world["weight"])):
        rows = np.flatnonzero(client == c)
        mix = po["currency_by_country"].get(world["country"][c], po["currency_by_country"]["default"])
        codes = np.array([CURRENCIES.index(k) for k in mix])
        currency[rows] = codes[choice_shares(rng, mix, len(rows))]
    d0, d1 = po["execution_delay_seconds"]
    executed = ts + rng.integers(d0, d1 + 1, n)

    rail = np.select(
        [currency == 0, currency == 1, (currency == 2) | (currency == 3)],
        [RAILS.index("sepa"), RAILS.index("faster_payments"), RAILS.index("swift")],
        RAILS.index("swift"),
    )
    launch = day_ts(po["elixir_launch"])
    elixir = (currency == 4) & (executed >= launch) & (rng.random(n) < po["elixir_share_after_launch"])
    rail = np.where(elixir, RAILS.index("elixir"), rail)

    eur = np.clip(
        po["amount_median_eur"] * np.exp(rng.normal(0.0, po["amount_sigma"], n)), po["amount_min_eur"], po["amount_max_eur"]
    )
    big = po["large_swift"]
    large = (rail == RAILS.index("swift")) & (rng.random(n) < big["share"])
    eur = np.where(large, rng.uniform(big["min_eur"], big["max_eur"], n), eur)
    rate = np.ones(n)
    fx_rows = currency > 0
    rate[fx_rows] = mid_at(fx, currency[fx_rows], ts[fx_rows]) / 1_000_000
    amount = np.rint(eur * rate * 100).astype(np.int64)

    order = np.lexsort((rng.random(n), ts))
    return {
        "id": np.array([f"po_{i:06d}" for i in range(1, n + 1)], dtype=object),
        "ts": ts[order],
        "executed": executed[order],
        "client": client[order],
        "currency": currency[order],
        "rail": rail[order],
        "amount": amount[order],
    }
