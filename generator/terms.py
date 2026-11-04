"""Reads contract YAML files and the interchange reference for the generator's own fee calculation."""

import csv
from pathlib import Path

import numpy as np
import yaml

from generator.common import CARD_TYPES, REGIONS, SCHEMES


def load_contracts(directory):
    """{counterparty: [version dicts sorted by version]}; each version has `by_kind` and `payout_fees`."""
    out = {}
    for path in sorted(Path(directory).glob("*.yml")):
        doc = yaml.safe_load(path.read_text())
        doc["by_kind"] = {}
        doc["payout_fees"] = {}
        doc["source_file"] = path.as_posix()
        for term in doc["terms"]:
            if term["kind"] == "payout_fee":
                doc["payout_fees"][term["rail"]] = term
            else:
                doc["by_kind"][term["kind"]] = term
        out.setdefault(doc["counterparty"], []).append(doc)
    for versions in out.values():
        versions.sort(key=lambda d: d["version"])
    return out


def version_index(versions, local_ts):
    """Index of the version in force at each local timestamp (contract time zone)."""
    starts = np.array([np.datetime64(v["effective_from"], "s").astype(np.int64) for v in versions])
    idx = np.searchsorted(starts, np.asarray(local_ts), side="right") - 1
    if (idx < 0).any():
        raise ValueError(f"event before the first version of {versions[0]['contract_id']}")
    return idx


def tier_index(tiers, volume):
    """Index of the tier whose exclusive upper bound `up_to_minor` the volume is below."""
    bounds = np.array([t["up_to_minor"] if t["up_to_minor"] is not None else np.iinfo(np.int64).max for t in tiers])
    return np.searchsorted(bounds, np.asarray(volume), side="right")


def load_interchange(path):
    """Arrays [scheme, card_type, region] of interchange_bps, scheme_fee_bps, scheme_fee_fixed_minor."""
    shape = (len(SCHEMES), len(CARD_TYPES), len(REGIONS))
    ic, sf, fixed = np.zeros(shape, np.int64), np.zeros(shape, np.int64), np.zeros(shape, np.int64)
    with open(path) as f:
        for row in csv.DictReader(f):
            k = SCHEMES.index(row["card_scheme"]), CARD_TYPES.index(row["card_type"]), REGIONS.index(row["card_region"])
            ic[k], sf[k], fixed[k] = int(row["interchange_bps"]), int(row["scheme_fee_bps"]), int(row["scheme_fee_fixed_minor"])
    return ic, sf, fixed
