"""Planted anomalies X01..: billing patterns that no contract rule describes (data contract section 8.8).

They are appended after the D planting, so every D, N and L draw is unchanged. An anomaly line is a provider
line of its own (its own fee component); `correct` is 0 because no contract term allows the charge.
"""

import datetime as dt

import numpy as np

from generator.billing import NG_COMPONENTS, PAYMENT, concat
from generator.common import day_ts, eea_consumer, round_div

SEGMENTS = {"all", "eea_consumer", "other"}


def _segment_mask(lines, segment):
    eea = eea_consumer(lines["card_type"], lines["region"])
    return {"all": np.ones(len(eea), bool), "eea_consumer": eea, "other": ~eea}[segment]


def plant_northgate(cfg, lines, info):
    """Append one line per Northgate payment that an enabled anomaly covers; records its specs in info."""
    lines["anomaly"] = np.full(len(lines["ts"]), "", dtype=object)
    info["extra_line_types"] = []
    info["anomalies"] = []
    base = {k: np.asarray(v) for k, v in lines.items()}
    tables = []
    for anomaly_id, spec in sorted((cfg.get("anomalies") or {}).items()):
        if not spec.get("enabled", True):
            continue
        if spec["provider"] != "northgate":
            raise ValueError(f"{anomaly_id}: only Northgate anomalies are supported (a Northgate line has its own fee type)")
        if spec["segment"] not in SEGMENTS:
            raise ValueError(f"{anomaly_id}: segment must be one of {sorted(SEGMENTS)}")
        component = len(NG_COMPONENTS) + len(info["extra_line_types"])
        info["extra_line_types"].append(spec["line_type"])
        # One line per real payment from the start date (UTC) on; payments missing from the ledger (D14) are left
        # out so that an anomaly line is never also an unknown charge.
        sel = np.flatnonzero(
            (base["component"] == NG_COMPONENTS.index("markup")) & (base["ev_type"] == PAYMENT) & ~base["phantom"]
            & (base["ts"] >= day_ts(dt.date.fromisoformat(str(spec["start"])))) & _segment_mask(base, spec["segment"])
        )
        new = {k: v[sel].copy() for k, v in base.items()}
        new["component"] = np.full(len(sel), component)
        new["correct"] = np.zeros(len(sel), np.int64)
        new["billed"] = round_div(new["amount"] * int(spec["bps"]), 10000, info["mode"])
        new["truth"] = np.full(len(sel), "", dtype=object)
        new["taken"] = np.zeros(len(sel), bool)
        new["dup_of"] = np.full(len(sel), -1)
        new["exported"] = np.ones(len(sel), bool)
        new["anomaly"] = np.full(len(sel), anomaly_id, dtype=object)
        tables.append(new)
        info["anomalies"].append({"anomaly_id": anomaly_id, **spec})
    if tables:
        lines.update(concat([base, *tables]))


def truth_rows(lines, line_ids, info):
    """truth.anomalies rows: one per planted anomaly, with its exported lines and billed money."""
    out = []
    for a in info["anomalies"]:
        idx = np.flatnonzero((lines["anomaly"] == a["anomaly_id"]) & (line_ids != ""))
        out.append((a["anomaly_id"], a["provider"], a["line_type"].lower(), a["line_type"], a["segment"], str(a["start"]),
                    int(a["bps"]), len(idx), int(lines["billed"][idx].sum()), "EUR"))
    return out
