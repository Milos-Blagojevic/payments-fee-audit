"""Generates the whole synthetic world: raw files under data/raw and truth under data/truth."""

import json
import shutil
from pathlib import Path

import numpy as np

from generator import billing, client_billing, discrepancies, exports
from generator.billing import CHARGEBACK, PAYMENT, REFUND
from generator.common import month_str, write_csv
from generator.ledger import build_fx, build_payments, build_payouts, build_refunds_chargebacks
from generator.terms import load_contracts, load_interchange
from generator.world import build_world

REPO = Path(__file__).resolve().parents[1]
FALLBACK_WINDOW = 48 * 3600


def unique_fallback_key(client, amount, ts):
    """True where no other event of the same table has the same client and amount within +-48 h."""
    order = np.lexsort((ts, amount, client))
    c, a, t = client[order], amount[order], ts[order]
    same = (c[1:] == c[:-1]) & (a[1:] == a[:-1]) & (t[1:] - t[:-1] <= FALLBACK_WINDOW)
    clash = np.r_[False, same] | np.r_[same, False]
    out = np.empty(len(order), bool)
    out[order] = ~clash
    return out


def _flatten(prefix, value, out):
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    else:
        out.append((prefix, json.dumps(value, default=str)))
    return out


def generate(cfg, out=REPO, contracts_dir=REPO / "contracts", interchange_path=REPO / "dbt/seeds/interchange_table_v1.csv"):
    """Write raw files and truth under out/data; return the in-memory tables (for calibration and tests)."""
    out = Path(out)
    for sub in ("data/raw", "data/truth"):
        shutil.rmtree(out / sub, ignore_errors=True)

    world = build_world(cfg)
    fx = build_fx(cfg)
    pay = build_payments(cfg, world)
    refunds, chargebacks = build_refunds_chargebacks(cfg, pay)
    payouts = build_payouts(cfg, world, fx)
    phantom = discrepancies.pick_phantoms(cfg, pay, refunds, chargebacks)

    providers = load_contracts(Path(contracts_dir) / "providers")
    interchange = load_interchange(interchange_path)
    ng, ng_info = billing.northgate(cfg, pay, refunds, chargebacks, phantom, providers, interchange)
    bp, bp_info = billing.brightpay(cfg, pay, refunds, chargebacks, phantom, providers)
    ks, ks_info = billing.kestrel(cfg, payouts, fx, providers)

    discrepancies.plant_northgate(cfg, ng, ng_info)
    discrepancies.plant_brightpay(cfg, bp, bp_info)
    discrepancies.plant_kestrel(cfg, ks, ks_info, fx)

    unique_key = {
        PAYMENT: unique_fallback_key(pay["client"], pay["amount"], pay["ts"]),
        REFUND: unique_fallback_key(pay["client"][refunds["payment"]], refunds["amount"], refunds["ts"]),
        CHARGEBACK: unique_fallback_key(pay["client"][chargebacks["payment"]], chargebacks["amount"], chargebacks["ts"]),
        "payout": unique_fallback_key(payouts["client"] * 10 + payouts["currency"], payouts["amount"], payouts["ts"]),
    }
    noise = exports.Noise()
    exports.ledger(cfg, out, world, pay, refunds, chargebacks, payouts, phantom)
    exports.fx_files(out, fx)
    ng_ids, ng_events, ng_totals = exports.northgate(cfg, out, ng, ng_info, pay, refunds, chargebacks, world, unique_key, noise)
    bp_ids, bp_events, bp_totals = exports.brightpay(cfg, out, bp, bp_info, pay, refunds, chargebacks, world, unique_key, noise)
    months = billing.period_months(cfg)
    ks_ids, ks_events, ks_totals = exports.kestrel(cfg, out, ks, months, payouts, world, unique_key, noise)
    invoices = exports.invoices(cfg, out, months, {"northgate": ng_totals, "brightpay": bp_totals, "kestrel": ks_totals})

    agreements = load_contracts(Path(contracts_dir) / "clients")
    clients = client_billing.compute(cfg, world, pay, payouts, phantom, fx, agreements)
    client_billing.write(cfg, out, world, clients)

    labels = month_str(months)
    truth = discrepancies.truth_rows("northgate", ng, ng_ids, ng_events, labels)
    truth += discrepancies.truth_rows("brightpay", bp, bp_ids, bp_events, labels)
    for i in np.flatnonzero(ks["truth"] != ""):
        truth.append((ks["truth"][i], "kestrel", labels[ks["month"][i]], ks_events[i], [ks_ids[i]],
                      int(ks["t_correct"][i]), int(ks["t_billed"][i])))
    truth.sort(key=lambda r: (r[0], r[1], r[2], r[3], r[4]))
    _write_truth(cfg, out, truth, clients["leakage"], noise.rows)
    return {
        "cfg": cfg, "world": world, "payments": pay, "refunds": refunds, "chargebacks": chargebacks, "payouts": payouts,
        "phantom": phantom, "northgate": ng, "northgate_info": ng_info, "brightpay": bp, "brightpay_info": bp_info,
        "kestrel": ks, "months": labels, "totals": {"northgate": ng_totals, "brightpay": bp_totals, "kestrel": ks_totals},
        "invoices": invoices, "clients": clients, "truth": truth, "noise": noise.rows,
    }


def _write_truth(cfg, out, truth, leakage, noise_rows):
    base = out / "data/truth"
    counters = {}
    disc = []
    for code, provider, month, event_id, ids, correct, billed in truth:
        counters[code] = counters.get(code, 0) + 1
        disc.append((f"{code}-{counters[code]:05d}", code, provider, month, event_id, json.dumps(ids), correct, billed,
                     billed - correct, "EUR"))
    write_csv(base / "discrepancies.csv",
              ["discrepancy_id", "truth_id", "provider", "month", "event_id", "line_ids", "correct_minor", "billed_minor",
               "difference_minor", "currency"], list(zip(*disc)) if disc else [[]] * 10)
    leak = [(code, client, month, comp, correct, billed, billed - correct) for code, client, month, comp, correct, billed in leakage]
    write_csv(base / "client_leakage.csv",
              ["truth_id", "client_id", "month", "component", "correct_minor", "billed_minor", "difference_minor"],
              list(zip(*leak)) if leak else [[]] * 7)
    rows = [(t, f, "" if r is None else r, line, ev) for t, f, r, line, ev in noise_rows]
    write_csv(base / "noise_events.csv", ["truth_id", "source_file", "source_row", "line_id", "event_id"],
              list(zip(*rows)) if rows else [[]] * 5)
    params = _flatten("", cfg, [])
    write_csv(base / "parameters.csv", ["parameter", "value"], list(zip(*params)))
