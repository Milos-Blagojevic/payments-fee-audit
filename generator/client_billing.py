"""Fernway's client invoices from the pricing agreements (data contract section 4.2), with leakage L01-L04.

Invoices are computed from the events in the ledger export (the June invoice therefore excludes the
lag day) and grouped by UTC month: payments by created_at, payouts by executed_at.
"""

import numpy as np

from generator.billing import period_months
from generator.common import (
    RAILS,
    SUCCEEDED,
    eea_consumer,
    month_of,
    month_str,
    round_div,
    stream,
    write_csv,
)
from generator.exports import RAW
from generator.ledger import mid_at, watermark
from generator.terms import tier_index, version_index

COMPONENTS = ["payment_fees", "payout_fees_sepa", "payout_fees_faster_payments", "payout_fees_swift",
              "payout_fees_elixir", "fx_markup", "platform_fee", "volume_discount", "promo_discount"]
DESCRIPTIONS = {
    "payment_fees": "Card payment fees",
    "payout_fees_sepa": "Payouts via SEPA",
    "payout_fees_faster_payments": "Payouts via Faster Payments",
    "payout_fees_swift": "Payouts via SWIFT",
    "payout_fees_elixir": "Payouts via Elixir",
    "fx_markup": "FX markup on non-EUR payouts",
    "platform_fee": "Platform fee",
    "volume_discount": "Volume discount",
    "promo_discount": "Promotional discount",
}


def _by_kind(doc, kind):
    return next((t for t in doc["terms"] if t["kind"] == kind), None)


def compute(cfg, world, pay, payouts, phantom, fx, agreements):
    """Correct and billed amounts per client x month x component, plus the leakage truth rows."""
    months = period_months(cfg)
    nm, nc = len(months), len(world["client_id"])
    wm = watermark(cfg)
    ids = world["client_id"].tolist()
    versions = [agreements[c] for c in ids]
    mode = versions[0][0]["rounding"]["mode"]
    shape = (nc, nm)

    ok = np.flatnonzero(~phantom & (pay["ts"] < wm) & (pay["status"] == SUCCEEDED))
    c, ts, a = pay["client"][ok], pay["ts"][ok], pay["amount"][ok]
    m = (month_of(ts) - months[0]).astype(np.int64)
    seg = eea_consumer(pay["card_type"][ok], pay["region"][ok])
    v = np.zeros(len(ok), np.int64)
    bps = np.zeros(len(ok), np.int64)
    fixed = np.zeros(len(ok), np.int64)
    promo_ok = np.zeros(len(ok), bool)
    for ci in range(nc):
        rows = np.flatnonzero(c == ci)
        v[rows] = version_index(versions[ci], ts[rows])
        for vi, doc in enumerate(versions[ci]):
            sel = rows[v[rows] == vi]
            segs = _by_kind(doc, "payment_fee_by_segment")["segments"]
            bps[sel] = np.where(seg[sel], segs["eea_consumer"]["bps"], segs["other"]["bps"])
            fixed[sel] = np.where(seg[sel], segs["eea_consumer"]["fixed_minor"], segs["other"]["fixed_minor"])
            promo = _by_kind(doc, "promo_discount")
            if promo:
                until = (np.datetime64(promo["valid_until"], "D") + np.timedelta64(1, "D")).astype("datetime64[s]").astype(np.int64)
                promo_ok[sel] = ts[sel] < until
    # Exact fee numerators in 1/10000 minor units.
    num = a * bps + fixed * 10000
    fee_num = np.zeros(shape, np.int64)
    np.add.at(fee_num, (c, m), num)
    promo_num = np.zeros(shape, np.int64)
    np.add.at(promo_num, (c[promo_ok], m[promo_ok]), num[promo_ok])
    volume = np.zeros(shape, np.int64)
    np.add.at(volume, (c, m), a)
    n_pay = np.zeros(shape, np.int64)
    np.add.at(n_pay, (c, m), 1)

    correct = {k: np.zeros(shape, np.int64) for k in COMPONENTS}
    qty = {k: np.zeros(shape, np.int64) for k in COMPONENTS}
    correct["payment_fees"] = round_div(fee_num, 10000, mode)
    qty["payment_fees"] = n_pay

    po = np.flatnonzero(payouts["ts"] < wm)
    pc, pex, pcur, prail, pamt = (payouts[k][po] for k in ("client", "executed", "currency", "rail", "amount"))
    pm = (month_of(pex) - months[0]).astype(np.int64)
    pv = np.zeros(len(po), np.int64)
    rail_fee = np.zeros(len(po), np.int64)
    fx_bps = np.zeros(len(po), np.int64)
    for ci in range(nc):
        rows = np.flatnonzero(pc == ci)
        pv[rows] = version_index(versions[ci], pex[rows])
        for vi, doc in enumerate(versions[ci]):
            sel = rows[pv[rows] == vi]
            rails = _by_kind(doc, "payout_fee_by_rail")["rails"]
            for r, name in enumerate(RAILS):
                on_rail = sel[prail[sel] == r]
                if len(on_rail) and name not in rails:
                    raise ValueError(f"{ids[ci]}: payout on rail {name} without a fee in version {doc['version']}")
                rail_fee[on_rail] = rails.get(name, {"fixed_minor": 0})["fixed_minor"]
            fx_bps[sel] = _by_kind(doc, "fx_markup")["bps"]
    for r, name in enumerate(RAILS):
        sel = prail == r
        np.add.at(correct[f"payout_fees_{name}"], (pc[sel], pm[sel]), rail_fee[sel])
        np.add.at(qty[f"payout_fees_{name}"], (pc[sel], pm[sel]), 1)
    fxr = np.flatnonzero(pcur > 0)
    eur = round_div(pamt[fxr] * 1_000_000, mid_at(fx, pcur[fxr], pex[fxr]), mode)
    fx_num = np.zeros(shape, np.int64)
    np.add.at(fx_num, (pc[fxr], pm[fxr]), eur * fx_bps[fxr])
    np.add.at(qty["fx_markup"], (pc[fxr], pm[fxr]), 1)
    correct["fx_markup"] = round_div(fx_num, 10000, mode)

    month_start = months.astype("datetime64[s]").astype(np.int64)
    pct = np.zeros(shape, np.int64)
    next_pct = np.zeros(shape, np.int64)
    promo_pct = np.zeros(shape, np.int64)
    promo_until = {}
    for ci in range(nc):
        mv = version_index(versions[ci], month_start)
        for mi, vi in enumerate(mv):
            doc = versions[ci][vi]
            correct["platform_fee"][ci, mi] = _by_kind(doc, "platform_fee")["amount_minor"]
            tiers = _by_kind(doc, "volume_discount_tiered")["tiers"]
            t = int(tier_index(tiers, volume[ci, mi]))
            pct[ci, mi] = tiers[t]["discount_pct"]
            next_pct[ci, mi] = tiers[min(t + 1, len(tiers) - 1)]["discount_pct"]
            promo = _by_kind(doc, "promo_discount")
            if promo:
                promo_pct[ci, mi] = promo["discount_pct"]
                promo_until[ci] = np.datetime64(promo["valid_until"], "M")
    qty["platform_fee"][:] = 1
    correct["volume_discount"] = -round_div(fee_num * pct, 1_000_000, mode)
    correct["promo_discount"] = -round_div(promo_num * promo_pct, 1_000_000, mode)

    billed = {k: val.copy() for k, val in correct.items()}
    leakage = []
    lk = cfg["leakage"]
    rng = stream(cfg, "leakage")

    # L01: the Elixir rail is never billed.
    billed["payout_fees_elixir"][:] = 0
    # L03: FX markup not billed for some clients.
    fx_clients = np.flatnonzero((correct["fx_markup"] > 0).sum(axis=1) >= 3)
    for ci in rng.choice(fx_clients, size=min(lk["L03"]["clients"], len(fx_clients)), replace=False):
        billed["fx_markup"][ci] = 0
    # L02: promotion applied to the whole month for months after its end date.
    last = months[-1]
    ended = [ci for ci, until in sorted(promo_until.items()) if until < last and until >= months[0]]
    for ci in rng.choice(ended, size=min(lk["L02"]["clients"], len(ended)), replace=False):
        end_m = int((promo_until[ci] - months[0]).astype(np.int64))
        for mi in range(end_m, min(nm, end_m + 1 + lk["L02"]["extra_months"])):
            billed["promo_discount"][ci, mi] = -int(round_div(fee_num[ci, mi] * promo_pct[ci, mi], 1_000_000, mode))
    # L04: discount of the next tier up.
    l04 = (next_pct > pct) & (fee_num > 0) & (rng.random(shape) < lk["L04"]["share"])
    billed["volume_discount"] = np.where(l04, -round_div(fee_num * next_pct, 1_000_000, mode), billed["volume_discount"])
    # Quantities as the invoice shows them: a discount line counts the month's payments whenever it is billed.
    qty["volume_discount"] = np.where(billed["volume_discount"] != 0, n_pay, 0)
    qty["promo_discount"] = np.where(billed["promo_discount"] != 0, n_pay, 0)

    labels = month_str(months)
    for k in COMPONENTS:
        code = {"payout_fees_elixir": "L01", "fx_markup": "L03", "promo_discount": "L02", "volume_discount": "L04"}.get(k)
        for ci, mi in zip(*np.nonzero(billed[k] != correct[k])):
            leakage.append((code, ids[ci], labels[mi], k, int(correct[k][ci, mi]), int(billed[k][ci, mi])))
    return {"months": labels, "correct": correct, "billed": billed, "qty": qty, "leakage": leakage}


def write(cfg, out, world, result):
    """One invoice file and one invoice-line file per month."""
    day = cfg["invoices"]["fernway_day"]
    ids = world["client_id"].tolist()
    for mi, label in enumerate(result["months"]):
        inv_date = str((np.datetime64(label, "M") + np.timedelta64(1, "M")).astype("datetime64[D]") + np.timedelta64(day - 1, "D"))
        invoices, lines = [], []
        for ci, cid in enumerate(ids):
            inv_id = f"FW-{label}-{cid}"
            total = 0
            n = 0
            for k in COMPONENTS:
                amount = int(result["billed"][k][ci, mi])
                if amount == 0 and k not in ("payment_fees", "platform_fee"):
                    continue
                n += 1
                total += amount
                lines.append((inv_id, str(n), k, DESCRIPTIONS[k], str(int(result["qty"][k][ci, mi])), str(amount)))
            invoices.append((inv_id, cid, label, inv_date, "EUR", str(total)))
        write_csv(out / f"{RAW}/fernway/client_invoices/fernway_client_invoices_{label}.csv",
                  ["invoice_id", "client_id", "period", "invoice_date", "currency", "total_minor"], list(zip(*invoices)))
        write_csv(out / f"{RAW}/fernway/client_invoice_lines/fernway_client_invoice_lines_{label}.csv",
                  ["invoice_id", "line_no", "component", "description", "quantity", "amount_minor"], list(zip(*lines)))

