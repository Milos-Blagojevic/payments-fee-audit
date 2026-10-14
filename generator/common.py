"""Shared helpers: config, random streams, codes, integer money and time."""

import datetime as dt
import zlib
import zoneinfo
from pathlib import Path

import numpy as np
import yaml

SCHEMES = ["visa", "mastercard"]
CARD_TYPES = ["consumer_debit", "consumer_credit", "commercial"]
REGIONS = ["domestic", "intra_eea", "inter_regional"]
STATUSES = ["succeeded", "declined", "failed"]
CARD_PROVIDERS = ["northgate", "brightpay"]
CURRENCIES = ["EUR", "GBP", "USD", "CHF", "PLN"]
RAILS = ["sepa", "faster_payments", "swift", "elixir"]
NORTHGATE, BRIGHTPAY = 0, 1
SUCCEEDED = 0


def load_config(path="config/generator.yml"):
    with open(path) as f:
        return yaml.safe_load(f)


def stream(cfg, name):
    """Independent random stream per generator step, derived from the seed."""
    return np.random.default_rng([cfg["seed"], zlib.crc32(name.encode())])


def choice_shares(rng, shares, size):
    """Draw indices into list(shares) with the given probabilities."""
    p = np.array(list(shares.values()), dtype=float)
    return rng.choice(len(p), size=size, p=p / p.sum())


def eea_consumer(card_type, region):
    return (card_type != 2) & (region != 2)


# ---- money -------------------------------------------------------------

def round_div(num, den, mode):
    """num / den rounded to an integer, half_up (away from zero) or half_even. den > 0."""
    num = np.asarray(num, dtype=np.int64)
    den = np.asarray(den, dtype=np.int64)
    sign = np.where(num < 0, -1, 1)
    q, r = np.divmod(np.abs(num), den)
    if mode == "half_up":
        q = q + (2 * r >= den)
    elif mode == "half_even":
        q = q + (2 * r > den) + ((2 * r == den) & (q % 2 == 1))
    else:
        raise ValueError(f"unknown rounding mode {mode}")
    return sign * q


def round_div_int(num, den, mode):
    """Python-int version of round_div for products that overflow int64."""
    sign = -1 if num < 0 else 1
    q, r = divmod(abs(num), den)
    if 2 * r > den or (2 * r == den and (mode == "half_up" or q % 2 == 1)):
        q += 1
    return sign * q


def fmt_major(minor, decimal="."):
    """Integer minor units to a major-unit string with two decimals."""
    return [f"{'-' if v < 0 else ''}{abs(v) // 100}{decimal}{abs(v) % 100:02d}" for v in np.asarray(minor).tolist()]


def fmt_rate(micro):
    return [f"{v // 1_000_000}.{v % 1_000_000:06d}" for v in np.asarray(micro).tolist()]


# ---- time (int64 seconds since the Unix epoch, UTC) ----------------------

def day_ts(d):
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


def utc_offsets(ts, tz):
    """Offset in seconds of the time zone at each UTC timestamp (transitions are on whole hours)."""
    if tz == "UTC":
        return np.zeros(len(ts), dtype=np.int64)
    zone = zoneinfo.ZoneInfo(tz)
    hours, inverse = np.unique(np.asarray(ts) // 3600, return_inverse=True)
    offsets = np.array(
        [int(dt.datetime.fromtimestamp(int(h) * 3600, zone).utcoffset().total_seconds()) for h in hours],
        dtype=np.int64,
    )
    return offsets[inverse]


def local_ts(ts, tz):
    return np.asarray(ts) + utc_offsets(ts, tz)


def to_dt64(ts):
    return np.asarray(ts).astype("datetime64[s]")


def month_of(ts):
    return to_dt64(ts).astype("datetime64[M]")


def date_of(ts):
    return to_dt64(ts).astype("datetime64[D]")


def fmt_iso_z(ts):
    return np.char.add(np.datetime_as_string(to_dt64(ts), unit="s"), "Z")


def fmt_space(ts):
    return np.char.replace(np.datetime_as_string(to_dt64(ts), unit="s"), "T", " ")


def month_str(m):
    return np.datetime_as_string(np.asarray(m).astype("datetime64[M]"), unit="M")


def write_csv(path, header, columns, delimiter=","):
    """Write columns (equal-length sequences of str) as a CSV file."""
    import csv

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f, delimiter=delimiter, lineterminator="\n")
        w.writerow(header)
        w.writerows(zip(*[np.asarray(c, dtype=object).tolist() for c in columns]))
