"""Calibration targets of the synthetic world, computed from the generated tables."""

from generator.common import BRIGHTPAY, NORTHGATE, SUCCEEDED

LINE_LEVEL = ["D01", "D03", "D04", "D06", "D07", "D08", "D09", "D11", "D12", "D13", "D14", "D15"]
MONTH_LEVEL = ["D02", "D05", "D10"]
NOISE = [f"N0{i}" for i in range(1, 9)]
LEAKAGE = ["L01", "L02", "L03", "L04"]


def provider_fees(g):
    """Billed provider fees in minor units: card fees plus Kestrel payout fees and FX spread cost."""
    ng, bp, ks = g["northgate"], g["brightpay"], g["kestrel"]
    fxr = ks["currency"] > 0
    return {
        "northgate": int(ng["billed"][ng["exported"]].sum()),
        "brightpay": int(bp["billed"][bp["exported"]].sum()),
        "kestrel": int(ks["fee_billed"].sum() + (ks["debit_billed"][fxr] - ks["eur_mid"][fxr]).sum()),
    }


def metrics(g):
    """Rows of (metric, value, low, high, formatted value, formatted range)."""
    pay = g["payments"]
    ok = (pay["status"] == SUCCEEDED) & ~g["phantom"]
    volume = pay["amount"][ok].sum()
    fees = provider_fees(g)
    by_provider = {p: pay["amount"][ok & (pay["provider"] == p)].sum() for p in (NORTHGATE, BRIGHTPAY)}
    over = sum(r[6] - r[5] for r in g["truth"] if r[6] > r[5] and r[0] != "D15")
    ng_info, bp_info = g["northgate_info"], g["brightpay_info"]
    threshold = ng_info["versions"][0]["by_kind"]["markup_bps_tiered"]["tiers"][0]["up_to_minor"]
    counts = {}
    for r in g["truth"]:
        counts[r[0]] = counts.get(r[0], 0) + 1
    for r in g["clients"]["leakage"]:
        counts[r[0]] = counts.get(r[0], 0) + 1
    for r in g["noise"]:
        counts[r[0]] = counts.get(r[0], 0) + 1

    rows = [
        ("card payments (succeeded)", int(ok.sum()), 350_000, 450_000, f"{int(ok.sum()):,}", "350,000-450,000"),
        ("card volume, EUR", volume / 100, 20e6, 35e6, f"{volume / 100:,.0f}", "20M-35M"),
        ("provider fees / volume, northgate", fees["northgate"] / by_provider[NORTHGATE], 0.006, 0.011,
         f"{fees['northgate'] / by_provider[NORTHGATE]:.3%}", "0.6%-1.1%"),
        ("provider fees / volume, brightpay", fees["brightpay"] / by_provider[BRIGHTPAY], 0.014, 0.020,
         f"{fees['brightpay'] / by_provider[BRIGHTPAY]:.3%}", "1.4%-2.0%"),
        ("planted overcharges / provider fees", over / sum(fees.values()), 0.02, 0.06,
         f"{over / sum(fees.values()):.2%} (EUR {over / 100:,.0f} of {sum(fees.values()) / 100:,.0f})", "2%-6%"),
        ("northgate months above EUR 2.5M", int((ng_info["volume"] >= threshold).sum()), 2, None,
         str(int((ng_info["volume"] >= threshold).sum())), ">= 2"),
        ("northgate months below EUR 2.5M", int((ng_info["volume"] < threshold).sum()), 1, None,
         str(int((ng_info["volume"] < threshold).sum())), ">= 1"),
        ("brightpay months EEA consumer above EUR 1.5M", int((bp_info["eea_volume"] > bp_info["threshold"][0]).sum()), 2,
         None, str(int((bp_info["eea_volume"] > bp_info["threshold"][0]).sum())), ">= 2"),
    ]
    for code in LINE_LEVEL:
        rows.append((f"{code} planted (lines or events)", counts.get(code, 0), 10, None, str(counts.get(code, 0)), ">= 10"))
    for code in MONTH_LEVEL:
        rows.append((f"{code} planted (months)", counts.get(code, 0), 2, None, str(counts.get(code, 0)), ">= 2"))
    for code in NOISE + LEAKAGE:
        rows.append((f"{code} planted", counts.get(code, 0), 1, None, str(counts.get(code, 0)), ">= 1"))
    return rows


def in_range(value, low, high):
    return value >= low and (high is None or value <= high)


def report(g):
    """Print the calibration table; return True when every target is in range."""
    rows = metrics(g)
    width = max(len(r[0]) for r in rows)
    vwidth = max(len(r[4]) for r in rows)
    print(f"{'metric':<{width}}  {'value':>{vwidth}}  {'range':<16} status")
    ok = True
    for name, value, low, high, shown, rng in rows:
        good = in_range(value, low, high)
        ok &= good
        print(f"{name:<{width}}  {shown:>{vwidth}}  {rng:<16} {'in' if good else 'OUT'}")
    return ok

