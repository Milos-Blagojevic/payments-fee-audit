"""Writes the raw files: ledger, FX, provider exports with noise N01-N08, provider invoices."""

import datetime as dt

import numpy as np

from generator.billing import CHARGEBACK, MONTH, PAYMENT, REFUND
from generator.common import (
    CARD_PROVIDERS,
    CARD_TYPES,
    CURRENCIES,
    RAILS,
    REGIONS,
    SCHEMES,
    STATUSES,
    SUCCEEDED,
    date_of,
    eea_consumer,
    fmt_iso_z,
    fmt_major,
    fmt_rate,
    fmt_space,
    local_ts,
    month_of,
    month_str,
    stream,
    write_csv,
)
from generator.ledger import PAIRS, period, watermark

RAW = "data/raw"

NG_LINE_TYPES = ["INTERCHANGE", "SCHEME_FEE", "MARKUP", "FIXED_FEE", "REFUND_FEE", "MARKUP_CREDIT", "CHARGEBACK_FEE",
                 "MONTHLY_MINIMUM"]
NG_BRANDS = [["VISA", "Visa", "visa", "VISA "], ["MASTERCARD", "Mastercard", "MC", "mastercard"]]
NG_PRODUCTS = [["CONSUMER_DEBIT", "Consumer Debit", "consumer-debit"], ["CONSUMER_CREDIT", "Consumer Credit", "consumer-credit"],
               ["COMMERCIAL", "Commercial", "commercial "]]
NG_REGIONS = [["DOMESTIC", "Domestic"], ["INTRA_EEA", "Intra-EEA"], ["INTER_REGIONAL", "Inter-Regional"]]
BP_NETWORKS = [["visa", "Visa", "VISA"], ["mastercard", "MasterCard", "mc"]]
BP_TYPES = [["consumer_debit", "Consumer Debit", "debit"], ["consumer_credit", "Consumer Credit", "credit"],
            ["commercial", "Commercial", "business"]]
BP_REGIONS = [["domestic", "Domestic"], ["intra_eea", "intra-EEA"], ["inter_regional", "inter-regional"]]
BP_STATUS = ["captured", "declined", "failed"]
BP_TYPE = {PAYMENT: "payment", REFUND: "refund", CHARGEBACK: "chargeback"}
KST_RAILS = ["SEPA", "FASTER_PAYMENTS", "SWIFT", "ELIXIR"]
CURRENCY_VARIANTS = ["{c}", "{lc}", " {c}", "{c} ", "{t}"]


def _variant(table, codes, pick):
    """Label for each code; pick > 0 selects a non-canonical variant ('' for code -1)."""
    width = max(len(t) for t in table)
    grid = np.array([t + [t[-1]] * (width - len(t)) for t in table] + [[""] * width], dtype=object)
    lens = np.array([len(t) for t in table] + [2])
    codes = np.where(codes < 0, len(table), codes)
    k = np.where(pick == 0, 0, 1 + (pick - 1) % (lens[codes] - 1))
    return grid[codes, k]


def _currency(codes, noisy, rng):
    out = np.array([CURRENCIES[c] for c in codes.tolist()], dtype=object)
    for i in np.flatnonzero(noisy):
        c = out[i]
        out[i] = CURRENCY_VARIANTS[1 + rng.integers(0, 4)].format(c=c, lc=c.lower(), t=c.title())
    return out


def _event_keys(lines):
    key = lines["ev_type"].astype(np.int64) * 10**9 + np.maximum(lines["ev_idx"], 0)
    return np.unique(key, return_inverse=True)


def _shift_late(cfg, lines, tz, months, rng):
    """N04: events in the last days of a month go to the next month's file (not for the last month)."""
    spec = cfg["noise"]["N04"]
    uniq, inv = _event_keys(lines)
    draw = rng.random(len(uniq))[inv]
    day = date_of(local_ts(lines["ts"], tz))
    next_month_start = (month_of(local_ts(lines["ts"], tz)) + np.timedelta64(1, "M")).astype("datetime64[D]")
    late = (next_month_start - day).astype(np.int64) <= spec["last_days"]
    shift = late & (draw < spec["share"]) & (lines["ev_type"] != MONTH) & (lines["month"] < len(months) - 1)
    return lines["month"] + shift, shift


def _missing_ref(cfg, lines, unique_key, rng):
    """N06: whole events (no discrepancy, unambiguous fallback key) lose the provider reference."""
    uniq, inv = _event_keys(lines)
    dirty = np.zeros(len(uniq), bool)
    np.logical_or.at(dirty, inv, (lines["truth"] != "") | lines["taken"] | lines["lag"] | lines["phantom"])
    ok_key = np.zeros(len(lines["ts"]), bool)
    for t in (PAYMENT, REFUND, CHARGEBACK):
        sel = lines["ev_type"] == t
        ok_key[sel] = unique_key[t][lines["ev_idx"][sel]]
    eligible = np.zeros(len(uniq), bool)
    np.logical_or.at(eligible, inv, ok_key)
    pick = eligible & ~dirty & (rng.random(len(uniq)) < cfg["noise"]["N06"]["share"])
    return pick[inv]


def _event_ids(lines, pay, refunds, chargebacks):
    tables = {PAYMENT: pay["id"], REFUND: refunds["id"], CHARGEBACK: chargebacks["id"]}
    out = np.full(len(lines["ts"]), "", dtype=object)
    for t, ids in tables.items():
        sel = lines["ev_type"] == t
        out[sel] = ids[lines["ev_idx"][sel]]
    return out


class Noise:
    """Collects truth.noise_events rows."""

    def __init__(self):
        self.rows = []

    def add(self, truth_id, source_file, source_row, line_id="", event_id=""):
        self.rows.append((truth_id, source_file, source_row, line_id, event_id))


def _write_files(out, base, name, months, file_month, order, columns, header, dup_mask=None, delimiters=None):
    """One file per month under out/base; returns each line's (file, row) and the appended duplicate rows."""
    file_of = np.full(len(file_month), "", dtype=object)
    row_of = np.zeros(len(file_month), np.int64)
    dups = []
    columns = [np.asarray(c, dtype=object) for c in columns]
    for m, label in enumerate(months):
        rows = order[file_month[order] == m]
        path = f"{base}/{name}_{label}.csv"
        file_of[rows] = path
        row_of[rows] = np.arange(1, len(rows) + 1)
        extra = rows[dup_mask[rows]] if dup_mask is not None else rows[:0]
        dups += [(path, len(rows) + j + 1, r) for j, r in enumerate(extra)]
        all_rows = np.concatenate([rows, extra])
        write_csv(out / path, header, [c[all_rows] for c in columns], delimiter=(delimiters or {}).get(m, ","))
    return file_of, row_of, dups


def northgate(cfg, out, lines, info, pay, refunds, chargebacks, world, unique_key, noise):
    rng = stream(cfg, "northgate-export")
    months = month_str(info["months"])
    tz = info["versions"][0]["timezone"]
    keep = np.flatnonzero(lines["exported"])
    sub = {k: np.asarray(v)[keep] for k, v in lines.items()}
    n = len(keep)
    file_month, late = _shift_late(cfg, sub, tz, months, rng)
    no_ref = _missing_ref(cfg, sub, unique_key, rng)
    order = np.lexsort((sub["component"], sub["ev_idx"], sub["ev_type"], sub["ts"], file_month))
    ids = np.empty(n, dtype=object)
    ids[order] = [f"NG{i:09d}" for i in range(1, n + 1)]
    event_id = _event_ids(sub, pay, refunds, chargebacks)
    is_month = sub["ev_type"] == MONTH
    # Anomaly lines come last and draw no line-level noise, so the N05 and N01 draws of every other line are the
    # same with or without them (N04 and N06 are drawn per event and apply to all of an event's lines).
    nb = int((sub["anomaly"] == "").sum())
    assert (sub["anomaly"][:nb] == "").all()

    def draw(values, fill):
        return np.concatenate([values, np.full(n - nb, fill, values.dtype)])

    n05 = (draw(rng.random(nb), 1.0) < cfg["noise"]["N05"]["share"]) & ~is_month
    which = draw(rng.integers(0, 3, nb), 0)
    pick = draw(rng.integers(1, 4, nb), 1)
    brand_pick = np.where(n05 & (which == 0), pick, 0)
    product_pick = np.where(n05 & (which == 1), pick, 0)
    currency_noisy = n05 & (which == 2)

    comma_month = cfg["noise"]["N02"]["northgate_comma_month"]
    comma_idx = months.tolist().index(comma_month) if comma_month in months.tolist() else -1
    in_comma = file_month == comma_idx
    lt = fmt_space(local_ts(sub["ts"], tz))
    txn_amount = np.array(fmt_major(sub["amount"]), dtype=object)
    fee = np.array(fmt_major(sub["billed"]), dtype=object)
    txn_amount[in_comma] = np.char.replace(txn_amount[in_comma].astype(str), ".", ",")
    fee[in_comma] = np.char.replace(fee[in_comma].astype(str), ".", ",")
    txn_currency = _currency(np.zeros(n, np.int64), currency_noisy, rng)
    period_col = np.where(is_month, months[sub["month"]], "")
    columns = [
        ids,
        np.where(no_ref | is_month, "", event_id),
        np.where(is_month, "", world["client_id"][np.maximum(sub["client"], 0)]),
        np.where(is_month, "", lt),
        period_col,
        np.array(NG_LINE_TYPES + info["extra_line_types"], dtype=object)[sub["component"]],
        np.where(is_month, "", txn_amount),
        np.where(is_month, "", txn_currency),
        _variant(NG_BRANDS, sub["scheme"], brand_pick),
        _variant(NG_PRODUCTS, sub["card_type"], product_pick),
        _variant(NG_REGIONS, sub["region"], np.zeros(n, np.int64)),
        fee,
        np.full(n, "EUR", dtype=object),
    ]
    header = ["line_ref", "txn_ref", "merchant_ref", "txn_time", "period", "line_type", "txn_amount", "txn_currency",
              "card_brand", "card_product", "card_region", "fee_amount", "fee_currency"]
    n01_month = cfg["noise"]["N01"]["files"].get("northgate")
    dup = (file_month == (months.tolist().index(n01_month) if n01_month in months.tolist() else -1)) \
        & (sub["truth"] == "") & ~is_month & (draw(rng.random(nb), 1.0) < cfg["noise"]["N01"]["share"])
    base = f"{RAW}/northgate/settlement_lines"
    file_of, row_of, dups = _write_files(out, base, "northgate_settlement", months, file_month, order, columns, header,
                                         dup, {comma_idx: ";"})
    for path, row, r in dups:
        noise.add("N01", path, row, ids[r], event_id[r])
    if comma_idx >= 0:
        noise.add("N02", f"{base}/northgate_settlement_{comma_month}.csv", None)
    for m in months:
        noise.add("N03", f"{base}/northgate_settlement_{m}.csv", None)
    _record(noise, "N04", late, file_of, row_of, ids, event_id)
    _record(noise, "N05", n05, file_of, row_of, ids, event_id)
    _record(noise, "N06", no_ref, file_of, row_of, ids, event_id)
    _record(noise, "N07", sub["lag"], file_of, row_of, ids, event_id)

    line_ids = np.full(len(lines["ts"]), "", dtype=object)
    line_ids[keep] = ids
    totals = np.bincount(file_month, weights=sub["billed"], minlength=len(months)).astype(np.int64)
    return line_ids, _event_ids(lines, pay, refunds, chargebacks), totals


def _record(noise, code, mask, file_of, row_of, ids, event_id):
    for i in np.flatnonzero(mask):
        noise.add(code, file_of[i], int(row_of[i]), ids[i], event_id[i])


def brightpay(cfg, out, lines, info, pay, refunds, chargebacks, world, unique_key, noise):
    rng = stream(cfg, "brightpay-export")
    months = month_str(info["months"])
    is_month = lines["ev_type"] == MONTH
    keep = np.flatnonzero(lines["exported"] & ~is_month)
    sub = {k: np.asarray(v)[keep] for k, v in lines.items()}
    n = len(keep)

    # N08: some half-even ties rounded half-up instead (one minor unit more).
    seg = eea_consumer(sub["card_type"], sub["region"]).astype(int)
    bps = np.array([[b["other"]["bps"], b["eea_consumer"]["bps"]] for b in info["blended"]])[sub["version"], seg]
    product = sub["amount"] * bps
    tie = (product % 10000 == 5000) & ((product // 10000) % 2 == 0)
    clean_payment = (sub["ev_type"] == PAYMENT) & (sub["status"] == SUCCEEDED) & (sub["truth"] == "") & ~sub["taken"] & ~sub["lag"]
    n08 = tie & clean_payment & (rng.random(n) < cfg["noise"]["N08"]["share_of_ties"])
    sub["billed"] = sub["billed"] + n08
    lines["billed"][keep] = sub["billed"]

    file_month, late = _shift_late(cfg, sub, "UTC", months, rng)
    no_ref = _missing_ref(cfg, sub, unique_key, rng) & ~n08
    order = np.lexsort((sub["dup_of"], sub["ev_idx"], sub["ev_type"], sub["ts"], file_month))
    ids = np.empty(n, dtype=object)
    ids[order] = [f"bp_{i:09d}" for i in range(1, n + 1)]
    event_id = _event_ids(sub, pay, refunds, chargebacks)

    n05 = rng.random(n) < cfg["noise"]["N05"]["share"]
    which = rng.integers(0, 3, n)
    pick = rng.integers(1, 3, n)
    status = np.where(sub["ev_type"] == PAYMENT, np.array(BP_STATUS, dtype=object)[sub["status"]], "completed")
    columns = [
        ids,
        np.array([BP_TYPE[t] for t in sub["ev_type"].tolist()], dtype=object),
        status,
        np.where(no_ref, "", event_id),
        world["client_id"][sub["client"]],
        fmt_iso_z(sub["ts"]),
        sub["amount"].astype(str),
        _currency(np.zeros(n, np.int64), n05 & (which == 2), rng),
        _variant(BP_NETWORKS, sub["scheme"], np.where(n05 & (which == 0), pick, 0)),
        _variant(BP_TYPES, sub["card_type"], np.where(n05 & (which == 1), pick, 0)),
        _variant(BP_REGIONS, sub["region"], np.zeros(n, np.int64)),
        sub["billed"].astype(str),
        np.full(n, "EUR", dtype=object),
    ]
    header = ["id", "type", "status", "merchant_reference", "sub_merchant", "created", "amount", "currency",
              "card_network", "card_type", "card_region", "fee", "fee_currency"]
    n01_month = cfg["noise"]["N01"]["files"].get("brightpay")
    dup = (file_month == (months.tolist().index(n01_month) if n01_month in months.tolist() else -1)) \
        & (sub["truth"] == "") & ~n08 & (rng.random(n) < cfg["noise"]["N01"]["share"])
    base = f"{RAW}/brightpay/transactions_export"
    file_of, row_of, dups = _write_files(out, base, "brightpay_transactions", months, file_month, order, columns,
                                         header, dup)
    for path, row, r in dups:
        noise.add("N01", path, row, ids[r], event_id[r])
    _record(noise, "N04", late, file_of, row_of, ids, event_id)
    _record(noise, "N05", n05, file_of, row_of, ids, event_id)
    _record(noise, "N06", no_ref, file_of, row_of, ids, event_id)
    _record(noise, "N07", sub["lag"], file_of, row_of, ids, event_id)
    _record(noise, "N08", n08, file_of, row_of, ids, event_id)
    for m in months:
        noise.add("N02", f"{base}/brightpay_transactions_{m}.csv", None)

    # Monthly adjustments file (rows only for non-zero adjustments).
    adj_rows = np.flatnonzero(is_month & lines["exported"])
    adj_ids = {}
    for m, label in enumerate(months):
        rows = adj_rows[lines["month"][adj_rows] == m]
        for r in rows:
            adj_ids[r] = f"adj_{label}_volume"
        write_csv(out / f"{RAW}/brightpay/adjustments/brightpay_adjustments_{label}.csv",
                  ["adjustment_id", "period", "type", "description", "amount", "currency"],
                  [[adj_ids[r] for r in rows], [label] * len(rows), ["volume_discount"] * len(rows),
                   ["Marginal volume discount on EEA consumer cards"] * len(rows),
                   [str(lines["billed"][r]) for r in rows], ["EUR"] * len(rows)])

    line_ids = np.full(len(lines["ts"]), "", dtype=object)
    line_ids[keep] = ids
    for r, i in adj_ids.items():
        line_ids[r] = i
    totals = np.bincount(file_month, weights=sub["billed"], minlength=len(months)).astype(np.int64)
    totals += np.bincount(lines["month"][adj_rows], weights=lines["billed"][adj_rows], minlength=len(months)).astype(np.int64)
    return line_ids, _event_ids(lines, pay, refunds, chargebacks), totals


def kestrel(cfg, out, rows, months_dt, payouts, world, unique_key, noise):
    rng = stream(cfg, "kestrel-export")
    months = month_str(months_dt)
    n = len(rows["ts"])
    order = np.argsort(rows["executed"], kind="stable")
    ids = np.empty(n, dtype=object)
    ids[order] = [f"KST-{i:07d}" for i in range(1, n + 1)]
    event_id = payouts["id"][rows["row"]]
    no_ref = (rows["truth"] == "") & ~rows["lag"] & unique_key["payout"][rows["row"]] \
        & (rng.random(n) < cfg["noise"]["N06"]["share"])
    n05 = rng.random(n) < cfg["noise"]["N05"]["share"]
    fxr = rows["currency"] > 0
    columns = [
        ids,
        np.where(no_ref, "", event_id),
        world["client_id"][rows["client"]],
        _currency(rows["currency"], n05, rng),
        fmt_major(rows["amount"]),
        np.array(KST_RAILS, dtype=object)[rows["rail"]],
        fmt_major(rows["fee_billed"]),
        np.where(fxr, np.array(fmt_rate(rows["applied_billed"]), dtype=object), ""),
        np.where(fxr, np.char.add(np.datetime_as_string((rows["rate_hour"] * 3600).astype("datetime64[s]"), unit="s"), "+00:00"), ""),
        fmt_major(rows["debit_billed"]),
        np.char.add(np.datetime_as_string(rows["executed"].astype("datetime64[s]"), unit="s"), "+00:00"),
    ]
    header = ["statement_line_id", "client_payout_ref", "client_id", "payout_currency", "payout_amount", "rail",
              "fee_eur", "fx_rate_applied", "rate_timestamp", "eur_debited", "executed_at"]
    base = f"{RAW}/kestrel/payouts_statement"
    file_of, row_of, _ = _write_files(out, base, "kestrel_payouts", months, rows["month"], order, columns, header)
    _record(noise, "N05", n05, file_of, row_of, ids, event_id)
    _record(noise, "N06", no_ref, file_of, row_of, ids, event_id)
    _record(noise, "N07", rows["lag"], file_of, row_of, ids, event_id)
    totals = np.bincount(rows["month"], weights=rows["fee_billed"], minlength=len(months)).astype(np.int64)
    return ids, event_id, totals


def invoices(cfg, out, months_dt, totals):
    """One invoice per provider and statement month; the total is the sum of the statement lines."""
    inv = cfg["invoices"]
    months = month_str(months_dt)
    dates = [(m + np.timedelta64(1, "M")).astype("datetime64[D]") for m in months_dt]
    rows = {"northgate": [], "brightpay": [], "kestrel": []}
    for i, m in enumerate(months):
        d = {p: str(dates[i] + np.timedelta64(inv[f"{p}_day"] - 1, "D")) for p in rows}
        rows["northgate"].append([f"NG-INV-{m.replace('-', '')}", m, d["northgate"], fmt_major([totals["northgate"][i]])[0], "EUR"])
        rows["brightpay"].append([f"BP-{m}-001", m, d["brightpay"], str(totals["brightpay"][i]), "EUR"])
        rows["kestrel"].append([f"KP{m.replace('-', '')}", m, d["kestrel"], fmt_major([totals["kestrel"][i]])[0], "EUR"])
    headers = {
        "northgate": ["invoice_no", "period", "invoice_date", "total_amount", "currency"],
        "brightpay": ["invoice_id", "billing_month", "issued_on", "total", "currency"],
        "kestrel": ["invoice_number", "statement_month", "invoice_date", "amount_eur", "currency"],
    }
    for p, r in rows.items():
        write_csv(out / f"{RAW}/{p}/invoices/{p}_invoices.csv", headers[p], list(zip(*r)))
    return {p: [(row[0], row[2]) for row in r] for p, r in rows.items()}


def ledger(cfg, out, world, pay, refunds, chargebacks, payouts, phantom):
    """Daily ledger files; the file for export date D holds the events created on D - 1 (UTC)."""
    start, end = period(cfg)
    wm = watermark(cfg)
    lag = cfg["ledger_lag_days"]
    in_ledger = ~phantom
    pays = np.flatnonzero(in_ledger)
    tables = {
        "payments": (pay["ts"][pays], [
            pay["id"][pays], world["client_id"][pay["client"][pays]], fmt_iso_z(pay["ts"][pays]), pay["amount"][pays].astype(str),
            np.full(len(pays), "EUR", dtype=object), np.array(SCHEMES, dtype=object)[pay["scheme"][pays]],
            np.array(CARD_TYPES, dtype=object)[pay["card_type"][pays]], np.array(REGIONS, dtype=object)[pay["region"][pays]],
            np.array(STATUSES, dtype=object)[pay["status"][pays]], np.array(CARD_PROVIDERS, dtype=object)[pay["provider"][pays]],
        ], ["payment_id", "client_id", "created_at", "amount_minor", "currency", "card_scheme", "card_type", "card_region",
            "status", "provider"]),
        "refunds": (refunds["ts"], [
            refunds["id"], pay["id"][refunds["payment"]], fmt_iso_z(refunds["ts"]), refunds["amount"].astype(str),
            np.full(len(refunds["ts"]), "EUR", dtype=object),
        ], ["refund_id", "payment_id", "created_at", "amount_minor", "currency"]),
        "chargebacks": (chargebacks["ts"], [
            chargebacks["id"], pay["id"][chargebacks["payment"]], fmt_iso_z(chargebacks["ts"]), chargebacks["amount"].astype(str),
            np.full(len(chargebacks["ts"]), "EUR", dtype=object),
        ], ["chargeback_id", "payment_id", "created_at", "amount_minor", "currency"]),
        "payouts": (payouts["ts"], [
            payouts["id"], world["client_id"][payouts["client"]], fmt_iso_z(payouts["ts"]), fmt_iso_z(payouts["executed"]),
            payouts["amount"].astype(str), np.array(CURRENCIES, dtype=object)[payouts["currency"]],
            np.array(RAILS, dtype=object)[payouts["rail"]], np.full(len(payouts["ts"]), "kestrel", dtype=object),
        ], ["payout_id", "client_id", "created_at", "executed_at", "amount_minor", "currency", "rail", "provider"]),
    }
    days = np.arange(start, wm, 86400)
    for name, (ts, cols, header) in tables.items():
        cols = [np.asarray(c, dtype=object) for c in cols]
        bounds = np.searchsorted(ts, np.append(days, wm))
        for i, day in enumerate(days):
            export = dt.datetime.fromtimestamp(int(day), dt.timezone.utc).date() + dt.timedelta(days=lag)
            rows = slice(bounds[i], bounds[i + 1])
            write_csv(out / f"{RAW}/ledger/{name}/ledger_{name}_{export.isoformat()}.csv", header, [c[rows] for c in cols])

    after = world["provider_after"]
    write_csv(out / f"{RAW}/fernway/clients/fernway_clients.csv",
              ["client_id", "client_name", "country", "card_provider", "card_provider_switch_date", "card_provider_after_switch"],
              [world["client_id"], world["client_name"], world["country"],
               [CARD_PROVIDERS[p] for p in world["provider"]],
               [str(np.datetime64(int(s), "s").astype("datetime64[D]")) if s >= 0 else "" for s in world["switch_ts"]],
               [CARD_PROVIDERS[a] if s >= 0 else "" for a, s in zip(after, world["switch_ts"])]])


def fx_files(out, fx):
    hours = fx["hour0"] + np.arange(fx["mid"].shape[1])
    ts = hours * 3600
    month = month_str(month_of(ts))
    stamp = fmt_iso_z(ts)
    for m in np.unique(month):
        sel = np.flatnonzero(month == m)
        pair = np.repeat(np.array(PAIRS, dtype=object), len(sel))
        write_csv(out / f"{RAW}/fx/mid_hourly/fx_mid_hourly_{m}.csv", ["pair", "hour_start_utc", "mid"],
                  [pair, np.tile(stamp[sel], len(PAIRS)), fmt_rate(fx["mid"][:, sel].ravel())])
