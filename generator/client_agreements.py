"""Renders Fernway's client pricing agreements (contracts/clients/*.yml) from the world and the config.

Run `python -m generator.client_agreements` after changing the world or `client_agreements` in the config;
the files are committed and a test checks they equal a fresh render.
"""

import argparse
from pathlib import Path

from generator.common import load_config, stream
from generator.world import build_world

RAIL_TITLES = {"sepa": "SEPA", "faster_payments": "Faster Payments", "swift": "SWIFT", "elixir": "Elixir"}


def agreement_terms(cfg, world):
    """Per client: the parameters both versions share."""
    a = cfg["client_agreements"]
    rng = stream(cfg, "agreements")
    out = []
    for i in range(len(world["client_id"])):
        tercile = min(2, int(world["size_rank"][i] * 3))
        promo = None
        if rng.random() < a["promo"]["share_of_clients"]:
            promo = {
                "discount_pct": int(rng.choice(a["promo"]["discount_pct"])),
                "valid_until": a["promo"]["valid_until"][rng.integers(0, len(a["promo"]["valid_until"]))],
            }
        out.append({
            "eea_bps": int(rng.choice(a["eea_consumer_bps"])),
            "other_bps": int(rng.choice(a["other_bps"])),
            "fx_bps": int(rng.choice(a["fx_markup_bps"])),
            "platform": int(a["platform_fee_minor"][tercile]),
            "promo": promo,
        })
    return out


def render(cfg, world, i, terms, version):
    a = cfg["client_agreements"]
    cid, name = world["client_id"][i], world["client_name"][i]
    rails = dict(a["rails_fixed_minor"])
    if version == 2:
        rails["elixir"] = a["elixir_fixed_minor"]
        header = f"# Fernway pricing agreement with {name}, version 2: adds the Elixir payout rail. Illustrative terms."
    else:
        header = f"# Fernway pricing agreement with {name}. Illustrative terms."
    effective = a["v2_effective_from"] if version == 2 else a["v1_effective_from"]
    lines = [
        header,
        f"contract_id: FW-{cid}",
        "party: client",
        f"counterparty: {cid}",
        f"name: {name}",
        f"version: {version}",
        f"effective_from: {effective}",
        "currency: EUR",
        "timezone: UTC",
        "rounding: {mode: half_up, level: invoice_line}",
        f"dispute_window_days: {a['dispute_window_days']}",
        "terms:",
        '  - clause: "2.1"',
        "    kind: payment_fee_by_segment",
        "    title: Fee per successful card payment by card segment",
        "    component: payment_fees",
        "    segments:",
        f"      eea_consumer: {{bps: {terms['eea_bps']}, fixed_minor: {a['eea_consumer_fixed_minor']}}}",
        f"      other: {{bps: {terms['other_bps']}, fixed_minor: {a['other_fixed_minor']}}}",
        '  - clause: "2.2"',
        "    kind: payout_fee_by_rail",
        "    title: Fee per payout by rail",
        "    rails:",
        *[f"      {rail}: {{fixed_minor: {fee}}}" for rail, fee in rails.items()],
        '  - clause: "2.3"',
        "    kind: fx_markup",
        "    title: FX markup on the EUR equivalent at mid of each non-EUR payout",
        "    component: fx_markup",
        f"    bps: {terms['fx_bps']}",
        '  - clause: "3.1"',
        "    kind: platform_fee",
        "    title: Monthly platform fee",
        "    component: platform_fee",
        f"    amount_minor: {terms['platform']}",
        '  - clause: "4.1"',
        "    kind: volume_discount_tiered",
        "    title: Discount on the month's payment fees by monthly processed volume, applied to the whole volume",
        "    component: volume_discount",
        "    basis: monthly_processed_volume",
        "    tiering: retroactive",
        "    tiers:",
        *[
            f"      - {{up_to_minor: {'null' if t['up_to_minor'] is None else t['up_to_minor']}, discount_pct: {t['discount_pct']}}}"
            for t in a["volume_discount_tiers"]
        ],
    ]
    if terms["promo"]:
        lines += [
            '  - clause: "4.2"',
            "    kind: promo_discount",
            "    title: Launch promotion on payment fees, for payments up to and including the end date",
            "    component: promo_discount",
            f"    discount_pct: {terms['promo']['discount_pct']}",
            f"    valid_until: {terms['promo']['valid_until']}",
        ]
    return "\n".join(lines) + "\n"


def render_all(cfg):
    """{file name: YAML text} for every client agreement version."""
    world = build_world(cfg)
    files = {}
    for i, terms in enumerate(agreement_terms(cfg, world)):
        for version in (1, 2):
            files[f"{world['client_id'][i].lower()}-v{version}.yml"] = render(cfg, world, i, terms, version)
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config/generator.yml")
    parser.add_argument("--out", default="contracts/clients")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.yml"):
        old.unlink()
    files = render_all(load_config(args.config))
    for name, text in files.items():
        (out / name).write_text(text)
    print(f"{len(files)} client agreement files written to {out}")


if __name__ == "__main__":
    main()

