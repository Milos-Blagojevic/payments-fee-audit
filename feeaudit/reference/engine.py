"""Expected provider charges per ledger event × component, plus provider × month rows."""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from typing import NamedTuple

import duckdb
import numpy as np

from feeaudit.reference import terms
from feeaudit.reference.contracts import Contract, ContractVersion


@dataclass(frozen=True)
class Payment:
    payment_id: str
    created_at: dt.datetime
    amount_minor: int
    currency: str
    card_scheme: str
    card_type: str
    card_region: str
    status: str
    provider: str


@dataclass(frozen=True)
class Refund:
    refund_id: str
    payment_id: str
    created_at: dt.datetime


@dataclass(frozen=True)
class Chargeback:
    chargeback_id: str
    payment_id: str
    created_at: dt.datetime


@dataclass(frozen=True)
class Payout:
    payout_id: str
    executed_at: dt.datetime
    amount_minor: int
    currency: str
    rail: str
    provider: str


class ExpectedCharge(NamedTuple):
    event_type: str
    event_id: str | None
    provider: str
    month: dt.date
    component: str
    contract_id: str
    contract_version: int
    clause: str
    expected_minor: int
    currency: str = "EUR"


# FX mids keyed by (pair, hour_start_utc).
FxMids = dict[tuple[str, dt.datetime], Fraction]
Interchange = dict[tuple[str, str, str, str], tuple[int, int, int]]


def parse_ts(value: str) -> dt.datetime:
    """ISO-8601 UTC timestamp with a trailing `Z`."""
    if not value.endswith("Z"):
        raise ValueError(f"timestamp without Z: {value!r}")
    return dt.datetime.fromisoformat(value).astimezone(dt.UTC)


def _charge(
    cv: ContractVersion, event_type: str, event_id: str | None, month: dt.date, component: str, clause: str, minor: int
) -> ExpectedCharge:
    return ExpectedCharge(
        event_type, event_id, cv.provider, month, component, cv.contract_id, cv.version, clause, minor
    )


def _one_term(cv: ContractVersion, kind: str) -> dict | None:
    found = cv.terms_of(kind)
    if len(found) > 1:
        raise ValueError(f"{cv.contract_id} v{cv.version}: more than one {kind} term")
    return found[0] if found else None


def _contract(contracts: dict[str, Contract], provider: str) -> Contract:
    if provider not in contracts:
        raise ValueError(f"no contract for provider {provider!r}")
    return contracts[provider]


def compute_expected_charges(
    contracts: dict[str, Contract],
    interchange: Interchange,
    payments: list[Payment],
    refunds: list[Refund],
    chargebacks: list[Chargeback],
    payouts: list[Payout],
    fx_mids: FxMids,
) -> list[ExpectedCharge]:
    """Every expected provider charge for the given ledger events, sorted deterministically."""
    rows: list[ExpectedCharge] = []
    event_months: dict[str, set[dt.date]] = defaultdict(set)
    month_volume: dict[tuple[str, dt.date], int] = defaultdict(int)
    segment_volume: dict[tuple[str, dt.date, str], int] = defaultdict(int)
    month_markup: dict[tuple[str, dt.date], int] = defaultdict(int)
    expected_markup: dict[str, int] = {}

    # Pass 1: monthly volumes of successful payments (contract-timezone months).
    for p in payments:
        if p.currency != "EUR":
            raise ValueError(f"payment {p.payment_id}: card payments must be EUR")
        contract = _contract(contracts, p.provider)
        month = contract.month_of(p.created_at)
        event_months[p.provider].add(month)
        if p.status == "succeeded":
            month_volume[p.provider, month] += p.amount_minor
            segment_volume[p.provider, month, terms.card_segment(p.card_type, p.card_region)] += p.amount_minor

    # Pass 2: per-payment components.
    for p in payments:
        contract = contracts[p.provider]
        cv = contract.version_at(p.created_at)
        month = contract.month_of(p.created_at)
        mode = cv.rounding_mode
        succeeded = p.status == "succeeded"
        if not succeeded and p.status not in ("declined", "failed"):
            raise ValueError(f"payment {p.payment_id}: unknown status {p.status!r}")
        segment = terms.card_segment(p.card_type, p.card_region)
        for term in cv.terms:
            kind, clause = term["kind"], term["clause"]
            if kind == "pass_through" and succeeded:
                key = (term["reference"], p.card_scheme, p.card_type, p.card_region)
                if key not in interchange:
                    raise ValueError(f"payment {p.payment_id}: no interchange reference for {key}")
                interchange_minor, scheme_minor = terms.pass_through(p.amount_minor, *interchange[key], mode)
                rows.append(_charge(cv, "payment", p.payment_id, month, "interchange", clause, interchange_minor))
                rows.append(_charge(cv, "payment", p.payment_id, month, "scheme_fee", clause, scheme_minor))
            elif kind == "markup_bps_tiered" and succeeded:
                if term["tiering"] != "retroactive":
                    raise ValueError(f"{cv.contract_id}: unsupported markup tiering {term['tiering']!r}")
                markup = terms.markup_retroactive(
                    p.amount_minor, month_volume[p.provider, month], term["tiers"], mode
                )
                expected_markup[p.payment_id] = markup
                month_markup[p.provider, month] += markup
                rows.append(_charge(cv, "payment", p.payment_id, month, term["component"], clause, markup))
            elif kind == "per_transaction_fixed" and succeeded:
                fee = terms.per_transaction_fixed(term["amount_minor"])
                rows.append(_charge(cv, "payment", p.payment_id, month, term["component"], clause, fee))
            elif kind == "blended_rate":
                fee = terms.blended_rate(
                    p.amount_minor, p.status, segment, term["segments"], term["failed_attempts"], mode
                )
                rows.append(_charge(cv, "payment", p.payment_id, month, term["component"], clause, fee))

    payments_by_id = {p.payment_id: p for p in payments}

    def original(event_id: str, payment_id: str) -> Payment:
        if payment_id not in payments_by_id:
            raise ValueError(f"{event_id}: original payment {payment_id} not in the ledger")
        return payments_by_id[payment_id]

    for r in refunds:
        provider = original(r.refund_id, r.payment_id).provider
        contract = contracts[provider]
        cv = contract.version_at(r.created_at)
        month = contract.month_of(r.created_at)
        event_months[provider].add(month)
        term = _one_term(cv, "refund")
        if term is None:
            continue
        fee, credit = terms.refund(
            term["fee_minor"], term["credit_original_markup"], expected_markup.get(r.payment_id, 0)
        )
        rows.append(_charge(cv, "refund", r.refund_id, month, "refund_fee", term["clause"], fee))
        if credit is not None:
            rows.append(_charge(cv, "refund", r.refund_id, month, "markup_credit", term["clause"], credit))

    for c in chargebacks:
        provider = original(c.chargeback_id, c.payment_id).provider
        contract = contracts[provider]
        cv = contract.version_at(c.created_at)
        month = contract.month_of(c.created_at)
        event_months[provider].add(month)
        term = _one_term(cv, "chargeback_fee")
        if term is None:
            continue
        fee = terms.chargeback_fee(term["amount_minor"])
        rows.append(_charge(cv, "chargeback", c.chargeback_id, month, "chargeback_fee", term["clause"], fee))

    for po in payouts:
        contract = _contract(contracts, po.provider)
        cv = contract.version_at(po.executed_at)
        month = contract.month_of(po.executed_at)
        event_months[po.provider].add(month)
        mode = cv.rounding_mode
        mid = Fraction(1)
        if po.currency != "EUR":
            hour = po.executed_at.replace(minute=0, second=0, microsecond=0)
            key = ("EUR" + po.currency, hour)
            if key not in fx_mids:
                raise ValueError(f"payout {po.payout_id}: no mid for {key[0]} at {hour.isoformat()}")
            mid = fx_mids[key]
        rail_terms = [t for t in cv.terms_of("payout_fee") if t["rail"] == po.rail]
        if len(rail_terms) != 1:
            raise ValueError(
                f"payout {po.payout_id}: {cv.contract_id} v{cv.version} has no single fee for rail {po.rail!r}"
            )
        fee = terms.payout_fee(po.amount_minor, mid, rail_terms[0], mode)
        rows.append(_charge(cv, "payout", po.payout_id, month, "payout_fee", rail_terms[0]["clause"], fee))
        cap_term = _one_term(cv, "fx_spread_cap")
        if cap_term is not None and po.currency != "EUR":
            cap_bps = cap_term["caps_bps"][po.currency]
            allowance = terms.fx_spread_cap(po.amount_minor, mid, cap_bps, mode)
            rows.append(_charge(cv, "payout", po.payout_id, month, "fx_conversion", cap_term["clause"], allowance))

    # Provider × month rows, under the version in force on the month's first local day.
    for provider, months in event_months.items():
        contract = contracts[provider]
        for month in months:
            cv = contract.version_on(month)
            for term in cv.terms_of("monthly_minimum"):
                if term["applies_to"] != "markup":
                    raise ValueError(f"{cv.contract_id}: unsupported minimum basis {term['applies_to']!r}")
                top_up = terms.monthly_minimum(term["amount_minor"], month_markup[provider, month])
                rows.append(_charge(cv, "provider_month", None, month, "monthly_minimum", term["clause"], top_up))
            for term in cv.terms_of("volume_discount"):
                if term["tiering"] != "marginal" or term["settlement"] != "monthly_adjustment":
                    raise ValueError(f"{cv.contract_id}: unsupported volume discount {term}")
                adjustment = terms.volume_adjustment(
                    segment_volume[provider, month, term["segment"]], term["tiers"], cv.rounding_mode
                )
                rows.append(
                    _charge(cv, "provider_month", None, month, term["component"], term["clause"], adjustment)
                )

    rows.sort(key=lambda r: (r.provider, r.event_type, r.event_id or "", r.month, r.component))
    return rows


def read_ledger(
    con: duckdb.DuckDBPyConnection,
) -> tuple[list[Payment], list[Refund], list[Chargeback], list[Payout], FxMids]:
    """Parse the VARCHAR tables of schema `raw` (data contract section 3)."""
    payments = [
        Payment(pid, parse_ts(ts), int(amount), cur, scheme, ctype, region, status, provider)
        for pid, ts, amount, cur, scheme, ctype, region, status, provider in con.execute(
            "select payment_id, created_at, amount_minor, currency, card_scheme, card_type,"
            " card_region, status, provider from raw.ledger__payments"
        ).fetchall()
    ]
    refunds = [
        Refund(rid, pid, parse_ts(ts))
        for rid, pid, ts in con.execute("select refund_id, payment_id, created_at from raw.ledger__refunds").fetchall()
    ]
    chargebacks = [
        Chargeback(cid, pid, parse_ts(ts))
        for cid, pid, ts in con.execute(
            "select chargeback_id, payment_id, created_at from raw.ledger__chargebacks"
        ).fetchall()
    ]
    payouts = [
        Payout(pid, parse_ts(executed), int(amount), cur, rail, provider)
        for pid, executed, amount, cur, rail, provider in con.execute(
            "select payout_id, executed_at, amount_minor, currency, rail, provider from raw.ledger__payouts"
        ).fetchall()
    ]
    fx_mids: FxMids = {}
    for pair, hour, mid in con.execute("select pair, hour_start_utc, mid from raw.fx__mid_hourly").fetchall():
        fx_mids[pair, parse_ts(hour)] = Fraction(mid)
    return payments, refunds, chargebacks, payouts, fx_mids


def write_expected_charges(con: duckdb.DuckDBPyConnection, rows: list[ExpectedCharge]) -> None:
    """Replace `reference.expected_charges` with the given rows."""
    columns = {
        "event_type": np.array([r.event_type for r in rows], dtype=object),
        "event_id": np.array([r.event_id for r in rows], dtype=object),
        "provider": np.array([r.provider for r in rows], dtype=object),
        "month": np.array([r.month.isoformat() for r in rows], dtype=object),
        "component": np.array([r.component for r in rows], dtype=object),
        "contract_id": np.array([r.contract_id for r in rows], dtype=object),
        "contract_version": np.array([r.contract_version for r in rows], dtype=np.int64),
        "clause": np.array([r.clause for r in rows], dtype=object),
        "expected_minor": np.array([r.expected_minor for r in rows], dtype=np.int64),
        "currency": np.array([r.currency for r in rows], dtype=object),
    }
    con.execute("create schema if not exists reference")
    con.register("_reference_rows", columns)
    try:
        con.execute(
            """
            create or replace table reference.expected_charges as
            select
                event_type::varchar as event_type,
                event_id::varchar as event_id,
                provider::varchar as provider,
                month::date as month,
                component::varchar as component,
                contract_id::varchar as contract_id,
                contract_version::integer as contract_version,
                clause::varchar as clause,
                expected_minor::bigint as expected_minor,
                currency::varchar as currency
            from _reference_rows
            """
        )
    finally:
        con.unregister("_reference_rows")
