"""Planted billing errors D01-D15 (data contract section 5). Each changes `billed` on lines it owns."""

import numpy as np

from generator.billing import BP_COMPONENTS, CHARGEBACK, MONTH, NG_COMPONENTS, PAYMENT, REFUND
from generator.common import (
    BRIGHTPAY,
    NORTHGATE,
    RAILS,
    SUCCEEDED,
    date_of,
    eea_consumer,
    local_ts,
    round_div,
    round_div_int,
    stream,
)
from generator.ledger import mid_at, watermark


def pick_phantoms(cfg, pay, refunds, chargebacks):
    """D14: payments that the provider bills but that never reach the ledger."""
    rng = stream(cfg, "D14")
    spec = cfg["discrepancies"]["D14"]
    phantom = np.zeros(len(pay["ts"]), bool)
    followed = np.zeros(len(pay["ts"]), bool)
    followed[refunds["payment"]] = True
    followed[chargebacks["payment"]] = True
    base = (pay["status"] == SUCCEEDED) & ~followed & (pay["ts"] < watermark(cfg)) & (pay["ts"] >= pay["ts"].min() + 86400)
    for provider, key in ((NORTHGATE, "northgate_events"), (BRIGHTPAY, "brightpay_events")):
        candidates = np.flatnonzero(base & (pay["provider"] == provider))
        phantom[rng.choice(candidates, size=spec[key], replace=False)] = True
    return phantom


def _init(lines, cfg):
    lines["billed"] = lines["correct"].copy()
    lines["truth"] = np.full(len(lines["ts"]), "", dtype=object)
    lines["lag"] = (lines["ts"] >= watermark(cfg)) & (lines["ev_type"] != MONTH)
    lines["taken"] = np.zeros(len(lines["ts"]), bool)
    lines["dup_of"] = np.full(len(lines["ts"]), -1)


def _mark(lines, idx, code):
    """Assign idx to a discrepancy; keeps only lines whose billed amount now differs."""
    idx = idx[lines["billed"][idx] != lines["correct"][idx]]
    assert (lines["truth"][idx] == "").all()
    lines["truth"][idx] = code
    return idx


def _free(lines):
    return (lines["truth"] == "") & ~lines["taken"] & ~lines["lag"] & ~lines["phantom"]


def _month_idx(info, month):
    return int((np.datetime64(month, "M") - info["months"][0]).astype(np.int64))


def plant_northgate(cfg, lines, info):
    d = cfg["discrepancies"]
    rng = stream(cfg, "northgate-discrepancies")
    _init(lines, cfg)
    comp = lines["component"]
    mode = info["mode"]
    last_month = len(info["months"]) - 1

    # D14: lines of phantom payments; the correct charge is zero.
    ph = np.flatnonzero(lines["phantom"])
    lines["correct"][ph] = 0
    _mark(lines, ph, "D14")

    # D01: stale markup rate in the first days after the latest amendment (contract-timezone dates).
    versions = info["versions"]
    amend = np.datetime64(versions[-1]["effective_from"], "D")
    local_day = date_of(local_ts(lines["ts"], versions[0]["timezone"]))
    window = (local_day >= amend) & (local_day < amend + np.timedelta64(d["D01"]["days"], "D"))
    sel = np.flatnonzero(_free(lines) & (comp == NG_COMPONENTS.index("markup")) & window
                         & (lines["version"] == len(versions) - 1) & (rng.random(len(comp)) < d["D01"]["share"]))
    old_bps = info["markup_bps"][lines["version"][sel] - 1, lines["month"][sel]]
    lines["billed"][sel] = round_div(lines["amount"][sel] * old_bps, 10000, mode)
    _mark(lines, sel, "D01")
    d01_months = set(np.unique(lines["month"][sel]).tolist())

    # D02: lower rate only once the running volume reaches the first threshold.
    for month in d["D02"]["months"]:
        m = _month_idx(info, month)
        if m in d01_months or m == last_month:
            raise ValueError(f"D02 month {month} must not be the D01 month or the last month")
        rows = np.flatnonzero((comp == NG_COMPONENTS.index("markup")) & (lines["month"] == m)
                              & (lines["ev_type"] == PAYMENT) & ~lines["phantom"])
        rows = rows[np.lexsort((lines["ev_idx"][rows], lines["ts"][rows]))]
        first = [v["by_kind"]["markup_bps_tiered"]["tiers"][0] for v in versions]
        threshold = np.array([t["up_to_minor"] for t in first])[lines["version"][rows]]
        if info["volume"][m] < threshold.max():
            raise ValueError(f"D02 month {month}: Northgate volume does not cross the first threshold")
        running = np.cumsum(lines["amount"][rows])
        early = rows[running < threshold]
        lines["billed"][early] = round_div(
            lines["amount"][early] * np.array([t["bps"] for t in first])[lines["version"][early]], 10000, mode)
        _mark(lines, early, "D02")

    # D03: interchange above the reference on some commercial cards.
    sel = np.flatnonzero(_free(lines) & (comp == NG_COMPONENTS.index("interchange")) & (lines["card_type"] == 2)
                         & (rng.random(len(comp)) < d["D03"]["share_of_commercial"]))
    lo, hi = d["D03"]["extra_bps"]
    extra = rng.integers(lo, hi + 1, len(sel))
    ref_bps = info["interchange_bps"][lines["scheme"][sel], lines["card_type"][sel], lines["region"][sel]]
    lines["billed"][sel] = round_div(lines["amount"][sel] * (ref_bps + extra), 10000, mode)
    _mark(lines, sel, "D03")

    # D04: markup credit missing on a refund.
    sel = np.flatnonzero(_free(lines) & (comp == NG_COMPONENTS.index("markup_credit"))
                         & (rng.random(len(comp)) < d["D04"]["share"]))
    lines["billed"][sel] = 0
    _mark(lines, sel, "D04")

    # D05: minimum charged in a month where the markup exceeded it.
    for month in d["D05"]["months"]:
        m = _month_idx(info, month)
        row = np.flatnonzero((comp == NG_COMPONENTS.index("monthly_minimum")) & (lines["month"] == m))
        if m == last_month or lines["correct"][row].any():
            raise ValueError(f"D05 month {month} is the last month or has a minimum due")
        lines["billed"][row] = d["D05"]["billed_minor"]
        _mark(lines, row, "D05")
    lines["exported"] = np.where(lines["ev_type"] == MONTH, lines["billed"] != 0, lines["truth"] != "D04")


def plant_brightpay(cfg, lines, info):
    d = cfg["discrepancies"]
    rng = stream(cfg, "brightpay-discrepancies")
    _init(lines, cfg)
    comp = lines["component"]
    mode = info["mode"]
    n = len(comp)
    payment = (lines["ev_type"] == PAYMENT)

    ph = np.flatnonzero(lines["phantom"])
    lines["correct"][ph] = 0
    _mark(lines, ph, "D14")

    ok = payment & (lines["status"] == SUCCEEDED)
    seg = eea_consumer(lines["card_type"], lines["region"])
    blended = info["blended"]
    v = lines["version"]

    def fee_at(rows, segment_key):
        bps = np.array([b[segment_key]["bps"] for b in blended])[v[rows]]
        fixed = np.array([b[segment_key]["fixed_minor"] for b in blended])[v[rows]]
        return round_div(lines["amount"][rows] * bps, 10000, mode) + fixed

    # D06: duplicates of some payments under a new line id (appended below).
    originals = np.flatnonzero(_free(lines) & ok & (rng.random(n) < d["D06"]["share"]))
    lines["taken"][originals] = True

    # D07: EEA consumer card billed at the other segment's rate.
    sel = np.flatnonzero(_free(lines) & ok & seg & (rng.random(n) < d["D07"]["share"]))
    lines["billed"][sel] = fee_at(sel, "other")
    _mark(lines, sel, "D07")

    # D08: fee on a declined or failed attempt.
    sel = np.flatnonzero(_free(lines) & payment & (lines["status"] != SUCCEEDED) & (rng.random(n) < d["D08"]["share"]))
    eea = sel[seg[sel]]
    other = sel[~seg[sel]]
    lines["billed"][eea] = fee_at(eea, "eea_consumer")
    lines["billed"][other] = fee_at(other, "other")
    _mark(lines, sel, "D08")

    # D09: wrong chargeback fee.
    sel = np.flatnonzero(_free(lines) & (lines["ev_type"] == CHARGEBACK) & (rng.random(n) < d["D09"]["share"]))
    lines["billed"][sel] = d["D09"]["billed_minor"]
    _mark(lines, sel, "D09")

    # D15: refund fee not charged (an undercharge).
    sel = np.flatnonzero(_free(lines) & (lines["ev_type"] == REFUND) & (rng.random(n) < d["D15"]["share"]))
    lines["billed"][sel] = 0
    _mark(lines, sel, "D15")

    # D10: monthly volume adjustment missing.
    last_month = len(info["months"]) - 1
    for month in d["D10"]["months"]:
        m = _month_idx(info, month)
        row = np.flatnonzero((comp == BP_COMPONENTS.index("volume_adjustment")) & (lines["month"] == m))
        if m == last_month or not (lines["correct"][row] < 0).all():
            raise ValueError(f"D10 month {month} is the last month or has no volume discount due")
        lines["billed"][row] = 0
        _mark(lines, row, "D10")

    dup = {k: np.asarray(val)[originals].copy() for k, val in lines.items()}
    dup["correct"][:] = 0
    dup["truth"][:] = "D06"
    dup["taken"][:] = True
    dup["dup_of"] = originals
    for k in lines:
        lines[k] = np.concatenate([lines[k], dup[k]])
    lines["exported"] = np.where(lines["ev_type"] == MONTH, lines["billed"] != 0, True)


def plant_kestrel(cfg, rows, info, fx):
    d = cfg["discrepancies"]
    rng = stream(cfg, "kestrel-discrepancies")
    mode = info["mode"]
    n = len(rows["ts"])
    rows["truth"] = np.full(n, "", dtype=object)
    rows["lag"] = rows["ts"] >= watermark(cfg)
    rows["fee_billed"] = rows["fee_correct"].copy()
    rows["applied_billed"] = rows["applied_correct"].copy()
    rows["debit_billed"] = rows["debit_correct"].copy()
    rows["rate_hour"] = rows["executed"] // 3600
    rows["t_correct"] = np.zeros(n, np.int64)
    rows["t_billed"] = np.zeros(n, np.int64)
    free = lambda: (rows["truth"] == "") & ~rows["lag"]  # noqa: E731
    fxr = rows["currency"] > 0

    # D13: SWIFT fee above the cap.
    swift = rows["rail"] == RAILS.index("swift")
    uncapped = np.zeros(n, np.int64)
    for vi, doc in enumerate(info["versions"]):
        term = doc["payout_fees"]["swift"]
        sel = swift & (rows["version"] == vi)
        uncapped[sel] = round_div(rows["eur_mid"][sel] * term["bps"], 10000, mode)
    caps = np.array([doc["payout_fees"]["swift"]["cap_minor"] for doc in info["versions"]])[rows["version"]]
    sel = np.flatnonzero(free() & swift & (uncapped > caps) & (rng.random(n) < d["D13"]["share"]))
    rows["fee_billed"][sel] = uncapped[sel]
    rows["truth"][sel] = "D13"
    rows["t_correct"][sel], rows["t_billed"][sel] = rows["fee_correct"][sel], uncapped[sel]

    # D11: spread above the cap.
    sel = np.flatnonzero(free() & fxr & (rng.random(n) < d["D11"]["share"]))
    lo, hi = d["D11"]["excess_bps"]
    spread = rows["cap_bps"][sel] + rng.uniform(lo, hi, len(sel))
    applied = np.rint(rows["mid"][sel] * (1 - spread / 10000)).astype(np.int64)
    debit = round_div(rows["amount"][sel] * 1_000_000, applied, mode)
    keep = debit > rows["allowance"][sel]
    sel, applied, debit = sel[keep], applied[keep], debit[keep]
    rows["applied_billed"][sel], rows["debit_billed"][sel] = applied, debit
    rows["truth"][sel] = "D11"
    rows["t_correct"][sel], rows["t_billed"][sel] = rows["allowance"][sel], debit

    # D12: the normal spread applied to the mid of a worse hour; the billed debit stays within the cap allowance.
    max_off = d["D12"]["max_hour_offset"]
    offsets = np.array([k for k in range(-max_off, max_off + 1) if k != 0])
    for i in np.flatnonzero(free() & fxr & (rng.random(n) < d["D12"]["share"])):
        amount, mid_exec, cur = int(rows["amount"][i]), int(rows["mid"][i]), rows["currency"][i]
        for k in rng.permutation(offsets):
            hour = rows["executed"][i] // 3600 + k
            mid_k = int(mid_at(fx, cur, hour * 3600))
            applied = int(np.rint(mid_k * (1 - rows["spread_bps"][i] / 10000)))
            debit = round_div_int(amount * 1_000_000, applied, mode)
            rescaled = round_div_int(amount * mid_k * 1_000_000, applied * mid_exec, mode)
            if rescaled < debit <= rows["allowance"][i]:
                rows["applied_billed"][i], rows["debit_billed"][i], rows["rate_hour"][i] = applied, debit, hour
                rows["truth"][i] = "D12"
                rows["t_correct"][i], rows["t_billed"][i] = rescaled, debit
                break


def truth_rows(provider, lines, line_ids, event_ids, months):
    """Truth records (truth_id, provider, month, event_id, line_ids, correct, billed) for Northgate or Brightpay."""
    out = []
    t = lines["truth"]
    by_event = {}
    for i in np.flatnonzero(lines["exported"] & (lines["ev_type"] == REFUND)):
        by_event.setdefault(int(lines["ev_idx"][i]), []).append(line_ids[i])
    for code in sorted(set(t[t != ""].tolist())):
        idx = np.flatnonzero(t == code)
        if code in ("D02", "D05", "D10"):
            for m in np.unique(lines["month"][idx]):
                rows = idx[lines["month"][idx] == m]
                ids = [line_ids[i] for i in rows if line_ids[i]]
                out.append((code, provider, months[m], "", ids, int(lines["correct"][rows].sum()),
                            int(lines["billed"][rows].sum())))
            continue
        for i in idx:
            ids = by_event.get(int(lines["ev_idx"][i]), []) if code == "D04" else [line_ids[i]]
            out.append((code, provider, months[lines["month"][i]], event_ids[i], ids, int(lines["correct"][i]),
                        int(lines["billed"][i])))
    return out
