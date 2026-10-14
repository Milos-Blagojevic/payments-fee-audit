"""Correct provider charges for every event, from the contract YAML (data contract section 4.1).

This is the generator's own implementation; the reference engine and dbt implement the same rules separately.
"""

import numpy as np

from generator.common import (
    BRIGHTPAY,
    CURRENCIES,
    NORTHGATE,
    RAILS,
    SUCCEEDED,
    eea_consumer,
    local_ts,
    month_of,
    round_div,
    stream,
)
from generator.ledger import mid_at, period, watermark
from generator.terms import tier_index, version_index

NG_COMPONENTS = [
    "interchange", "scheme_fee", "markup", "fixed_fee", "refund_fee", "markup_credit", "chargeback_fee", "monthly_minimum",
]
BP_COMPONENTS = ["transaction_fee", "refund_fee", "chargeback_fee", "volume_adjustment"]
PAYMENT, REFUND, CHARGEBACK, MONTH = 0, 1, 2, 3


def concat(tables):
    keys = tables[0].keys()
    return {k: np.concatenate([np.asarray(t[k]) for t in tables]) for k in keys}


def period_months(cfg):
    start, end = period(cfg)
    return np.arange(month_of(start), month_of(end - 1) + np.timedelta64(1, "M"))


def _month_index(months, ts_local):
    m = month_of(ts_local)
    idx = (m - months[0]).astype(np.int64)
    return np.where((idx >= 0) & (idx < len(months)), idx, -1)


def _lines(n, ev_type, ev_idx, component, ts, month, client, amount, scheme, card_type, region, correct, version, phantom):
    return {
        "ev_type": np.full(n, ev_type), "ev_idx": np.asarray(ev_idx), "component": np.full(n, component),
        "ts": np.asarray(ts), "month": np.asarray(month), "client": np.asarray(client), "amount": np.asarray(amount),
        "scheme": np.asarray(scheme), "card_type": np.asarray(card_type), "region": np.asarray(region),
        "correct": np.asarray(correct, dtype=np.int64), "version": np.asarray(version), "phantom": np.asarray(phantom),
    }


def _assert_same_tier(name, bounds, full, visible):
    for t in bounds:
        flipped = (full < t) != (visible < t)
        if flipped.any():
            raise AssertionError(
                f"{name}: monthly volume is so close to the threshold {t} that the ledger lag flips the tier; "
                "change the seed or the volume parameters"
            )


def northgate(cfg, pay, refunds, chargebacks, phantom, contracts, interchange):
    """Northgate fee lines (correct amounts) and the monthly volumes."""
    versions = contracts["northgate"]
    tz = versions[0]["timezone"]
    months = period_months(cfg)
    lt = local_ts(pay["ts"], tz)
    m_idx = _month_index(months, lt)
    ng = (pay["provider"] == NORTHGATE) & (pay["status"] == SUCCEEDED) & (m_idx >= 0)
    real = ng & ~phantom
    volume = np.bincount(m_idx[real], weights=pay["amount"][real], minlength=len(months)).astype(np.int64)
    visible = real & (pay["ts"] < watermark(cfg))
    vis_volume = np.bincount(m_idx[visible], weights=pay["amount"][visible], minlength=len(months)).astype(np.int64)
    bounds = sorted({t["up_to_minor"] for v in versions for t in v["by_kind"]["markup_bps_tiered"]["tiers"] if t["up_to_minor"]})
    _assert_same_tier("northgate", bounds, volume, vis_volume)

    v_idx = version_index(versions, lt)
    markup_bps = np.zeros((len(versions), len(months)), np.int64)
    for v, doc in enumerate(versions):
        tiers = doc["by_kind"]["markup_bps_tiered"]["tiers"]
        markup_bps[v] = np.array([tiers[i]["bps"] for i in tier_index(tiers, volume)])
    modes = [doc["rounding"]["mode"] for doc in versions]

    ic, sf, sf_fixed = interchange
    rows = np.flatnonzero(ng)
    a = pay["amount"][rows]
    key = pay["scheme"][rows], pay["card_type"][rows], pay["region"][rows]
    v = v_idx[rows]
    mode = modes[0]
    if len(set(modes)) != 1:
        raise ValueError("northgate versions with different rounding modes are not supported")
    fixed_amount = np.array([d["by_kind"]["per_transaction_fixed"]["amount_minor"] for d in versions])[v]
    markup = round_div(a * markup_bps[v, m_idx[rows]], 10000, mode)
    expected_markup = np.zeros(len(pay["ts"]), np.int64)
    expected_markup[rows] = markup
    payment_charges = {
        "interchange": round_div(a * ic[key], 10000, mode),
        "scheme_fee": round_div(a * sf[key], 10000, mode) + sf_fixed[key],
        "markup": markup,
        "fixed_fee": fixed_amount,
    }
    common = dict(ts=pay["ts"][rows], month=m_idx[rows], client=pay["client"][rows], amount=a,
                  scheme=key[0], card_type=key[1], region=key[2], version=v, phantom=phantom[rows])
    tables = [
        _lines(len(rows), PAYMENT, rows, NG_COMPONENTS.index(c), correct=amount, **common)
        for c, amount in payment_charges.items()
    ]

    for events, ev_type in ((refunds, REFUND), (chargebacks, CHARGEBACK)):
        p = events["payment"]
        e_lt = local_ts(events["ts"], tz)
        e_m = _month_index(months, e_lt)
        sel = np.flatnonzero((pay["provider"][p] == NORTHGATE) & (e_m >= 0))
        p = p[sel]
        ev_v = version_index(versions, e_lt[sel])
        common = dict(ts=events["ts"][sel], month=e_m[sel], client=pay["client"][p], amount=events["amount"][sel],
                      scheme=pay["scheme"][p], card_type=pay["card_type"][p], region=pay["region"][p],
                      version=ev_v, phantom=np.zeros(len(sel), bool))
        if ev_type == REFUND:
            fee = np.array([d["by_kind"]["refund"]["fee_minor"] for d in versions])[ev_v]
            tables.append(_lines(len(sel), REFUND, sel, NG_COMPONENTS.index("refund_fee"), correct=fee, **common))
            credit = np.array([d["by_kind"]["refund"]["credit_original_markup"] for d in versions])[ev_v]
            c_sel = np.flatnonzero(credit)
            tables.append(_lines(
                len(c_sel), REFUND, sel[c_sel], NG_COMPONENTS.index("markup_credit"),
                correct=-expected_markup[p[c_sel]], **{k: np.asarray(val)[c_sel] for k, val in common.items()},
            ))
        else:
            fee = np.array([d["by_kind"]["chargeback_fee"]["amount_minor"] for d in versions])[ev_v]
            tables.append(_lines(len(sel), CHARGEBACK, sel, NG_COMPONENTS.index("chargeback_fee"), correct=fee, **common))

    # Monthly minimum on markup: one line per month (amount 0 when not due; zero lines are not exported).
    month_markup = np.bincount(m_idx[real], weights=expected_markup[real], minlength=len(months)).astype(np.int64)
    month_start_local = months.astype("datetime64[s]").astype(np.int64)
    mv = version_index(versions, month_start_local)
    minimum = np.array([versions[i]["by_kind"]["monthly_minimum"]["amount_minor"] for i in mv])
    n = len(months)
    # Month-level lines carry the last second of the month (local time read as UTC); it only orders them last.
    month_end_ts = (months + np.timedelta64(1, "M")).astype("datetime64[s]").astype(np.int64) - 1
    tables.append(_lines(
        n, MONTH, np.full(n, -1), NG_COMPONENTS.index("monthly_minimum"), ts=month_end_ts,
        month=np.arange(n), client=np.full(n, -1), amount=np.zeros(n, np.int64), scheme=np.full(n, -1),
        card_type=np.full(n, -1), region=np.full(n, -1), correct=np.maximum(0, minimum - month_markup), version=mv,
        phantom=np.zeros(n, bool),
    ))
    lines = concat(tables)
    return lines, {"months": months, "volume": volume, "markup_bps": markup_bps, "versions": versions,
                   "expected_markup": expected_markup, "mode": mode, "interchange_bps": ic}


def brightpay(cfg, pay, refunds, chargebacks, phantom, contracts):
    """Brightpay rows (one per payment attempt, refund, chargeback) plus monthly volume adjustments."""
    versions = contracts["brightpay"]
    tz = versions[0]["timezone"]
    months = period_months(cfg)
    lt = local_ts(pay["ts"], tz)
    m_idx = _month_index(months, lt)
    v_idx = version_index(versions, lt)
    mode = versions[0]["rounding"]["mode"]
    seg = eea_consumer(pay["card_type"], pay["region"])

    bp = (pay["provider"] == BRIGHTPAY) & (m_idx >= 0)
    rows = np.flatnonzero(bp)
    a = pay["amount"][rows]
    v = v_idx[rows]
    blended = [d["by_kind"]["blended_rate"]["segments"] for d in versions]
    bps = np.array([[b["other"]["bps"], b["eea_consumer"]["bps"]] for b in blended])[v, seg[rows].astype(int)]
    fixed = np.array([[b["other"]["fixed_minor"], b["eea_consumer"]["fixed_minor"]] for b in blended])[v, seg[rows].astype(int)]
    ok = pay["status"][rows] == SUCCEEDED
    fee = np.where(ok, round_div(a * bps, 10000, mode) + fixed, 0)
    tables = [_lines(len(rows), PAYMENT, rows, 0, ts=pay["ts"][rows], month=m_idx[rows], client=pay["client"][rows],
                     amount=a, scheme=pay["scheme"][rows], card_type=pay["card_type"][rows], region=pay["region"][rows],
                     correct=fee, version=v, phantom=phantom[rows])]
    for events, ev_type, comp, kind, key in ((refunds, REFUND, 1, "refund", "fee_minor"),
                                             (chargebacks, CHARGEBACK, 2, "chargeback_fee", "amount_minor")):
        p = events["payment"]
        e_lt = local_ts(events["ts"], tz)
        e_m = _month_index(months, e_lt)
        sel = np.flatnonzero((pay["provider"][p] == BRIGHTPAY) & (e_m >= 0))
        p = p[sel]
        ev_v = version_index(versions, e_lt[sel])
        fee = np.array([d["by_kind"][kind][key] for d in versions])[ev_v]
        tables.append(_lines(len(sel), ev_type, sel, comp, ts=events["ts"][sel], month=e_m[sel], client=pay["client"][p],
                             amount=events["amount"][sel], scheme=pay["scheme"][p], card_type=pay["card_type"][p],
                             region=pay["region"][p], correct=fee, version=ev_v, phantom=np.zeros(len(sel), bool)))

    real = bp & ~phantom & (pay["status"] == SUCCEEDED) & seg
    volume = np.bincount(m_idx[real], weights=pay["amount"][real], minlength=len(months)).astype(np.int64)
    visible = real & (pay["ts"] < watermark(cfg))
    vis_volume = np.bincount(m_idx[visible], weights=pay["amount"][visible], minlength=len(months)).astype(np.int64)
    month_start = months.astype("datetime64[s]").astype(np.int64)
    mv = version_index(versions, month_start)
    adj = np.zeros(len(months), np.int64)
    bounds = set()
    for i, vi in enumerate(mv):
        tiers = versions[vi]["by_kind"]["volume_discount"]["tiers"]
        threshold = tiers[0]["up_to_minor"]
        bounds.add(threshold)
        if volume[i] > threshold:
            adj[i] = -round_div((volume[i] - threshold) * (tiers[0]["bps"] - tiers[1]["bps"]), 10000, mode)
    _assert_same_tier("brightpay", sorted(bounds), volume, vis_volume)
    n = len(months)
    month_end_ts = (months + np.timedelta64(1, "M")).astype("datetime64[s]").astype(np.int64) - 1
    tables.append(_lines(n, MONTH, np.full(n, -1), 3, ts=month_end_ts, month=np.arange(n), client=np.full(n, -1),
                         amount=np.zeros(n, np.int64), scheme=np.full(n, -1), card_type=np.full(n, -1),
                         region=np.full(n, -1), correct=adj, version=mv, phantom=np.zeros(n, bool)))
    lines = concat(tables)
    lines["status"] = np.where(lines["ev_type"] == PAYMENT, pay["status"][np.maximum(lines["ev_idx"], 0)], SUCCEEDED)
    return lines, {"months": months, "eea_volume": volume, "threshold": sorted(bounds), "mode": mode, "blended": blended,
                   "versions": versions}


def kestrel(cfg, payouts, fx, contracts):
    """Kestrel statement rows (one per payout executed in the period) with the correct fee and EUR debit."""
    rng = stream(cfg, "kestrel")
    versions = contracts["kestrel"]
    _, end = period(cfg)
    rows = np.flatnonzero(payouts["executed"] < end)
    ex = payouts["executed"][rows]
    v = version_index(versions, local_ts(ex, versions[0]["timezone"]))
    mode = versions[0]["rounding"]["mode"]
    cur = payouts["currency"][rows]
    rail = payouts["rail"][rows]
    amount = payouts["amount"][rows]
    n = len(rows)
    fxr = cur > 0
    mid = np.full(n, 1_000_000, np.int64)
    mid[fxr] = mid_at(fx, cur[fxr], ex[fxr])
    eur_mid = round_div(amount * 1_000_000, mid, mode)

    fee = np.full(n, -1, np.int64)
    cap_bps = np.zeros(n, np.int64)
    for vi, doc in enumerate(versions):
        caps = doc["by_kind"]["fx_spread_cap"]["caps_bps"]
        in_v = v == vi
        for c, code in enumerate(CURRENCIES[1:], start=1):
            cap_bps[in_v & (cur == c)] = caps[code]
        for r, name in enumerate(RAILS):
            sel = in_v & (rail == r)
            if not sel.any():
                continue
            term = doc["payout_fees"].get(name)
            if term is None:
                raise ValueError(f"payout on rail {name} under {doc['contract_id']} v{doc['version']} without a fee term")
            if "fixed_minor" in term:
                fee[sel] = term["fixed_minor"]
            else:
                fee[sel] = np.clip(round_div(eur_mid[sel] * term["bps"], 10000, mode), term["min_minor"], term["cap_minor"])
    lo, hi = cfg["fx"]["kestrel_spread_share_of_cap"]
    spread = rng.uniform(lo, hi, n) * cap_bps
    applied = np.where(fxr, np.rint(mid * (1 - spread / 10000)).astype(np.int64), 0)
    debit = np.where(fxr, round_div(amount * 1_000_000, np.maximum(applied, 1), mode), amount)
    allowance = np.where(fxr, round_div(amount * 10_000_000_000, mid * (10000 - cap_bps), mode), amount)
    if (debit > allowance).any():
        raise AssertionError("kestrel: a correct EUR debit is above the spread cap allowance")
    return {
        "row": rows, "ts": payouts["ts"][rows], "executed": ex, "client": payouts["client"][rows], "currency": cur,
        "rail": rail, "amount": amount, "version": v, "mid": mid, "eur_mid": eur_mid, "cap_bps": cap_bps,
        "spread_bps": spread, "fee_correct": fee, "applied_correct": applied, "debit_correct": debit,
        "allowance": allowance, "month": (month_of(ex) - period_months(cfg)[0]).astype(np.int64),
    }, {"mode": mode, "versions": versions}
