"""Fernway's clients: names, countries, sizes and card provider routing."""

import numpy as np

from generator.common import CARD_PROVIDERS, day_ts, stream

NAME_FIRST = [
    "Alder", "Birchwood", "Cobble", "Dunmore", "Ember", "Fernhill", "Gullwing", "Hartley", "Inkwell", "Juniper",
    "Kestwick", "Larkspur", "Millbrook", "Nettlebed", "Oakfield", "Pebblestone", "Quillon", "Rosemoor", "Saltmarsh",
    "Thistle", "Underhill", "Vellum", "Wrenfield", "Yewdale", "Ashgrove", "Brackwater", "Copperleaf", "Driftwood",
]
NAME_SECOND = ["Market", "Bazaar", "Goods", "Collective", "Exchange", "Trading Post", "Stalls", "Makers", "Swap", "Mart"]


def build_world(cfg):
    """Return the client table as a dict of arrays."""
    w = cfg["world"]
    rng = stream(cfg, "world")
    n = w["n_clients"]
    combos = [f"{a} {b}" for a in NAME_FIRST for b in NAME_SECOND]
    names = [combos[i] for i in rng.choice(len(combos), size=n, replace=False)]
    countries = list(w["countries"])
    p = np.array(list(w["countries"].values()), dtype=float)
    country = [countries[i] for i in rng.choice(len(countries), size=n, p=p / p.sum())]
    weight = rng.lognormal(0.0, w["size_sigma"], n)
    weight /= weight.sum()
    ticket_median = w["ticket_median_eur"] * np.exp(rng.normal(0.0, w["ticket_median_sigma"], n))

    # Route by expected card volume: clients in random order fill Northgate up to its share.
    volume = weight * ticket_median
    order = rng.permutation(n)
    start = np.cumsum(volume[order]) - volume[order]
    provider = np.ones(n, dtype=np.int64)
    provider[order[start < w["northgate_volume_share"] * volume.sum()]] = 0

    switch_ts = np.full(n, -1, dtype=np.int64)
    after = provider.copy()
    rank = np.argsort(np.argsort(weight)) / (n - 1)
    for sw in w["switches"]:
        src = CARD_PROVIDERS.index(sw["from"])
        candidates = np.flatnonzero((provider == src) & (switch_ts < 0) & (rank > 0.25) & (rank < 0.75))
        i = rng.choice(candidates)
        switch_ts[i] = day_ts(sw["date"])
        after[i] = 1 - src
    return {
        "client_id": np.array([f"CL{i:03d}" for i in range(1, n + 1)], dtype=object),
        "client_name": np.array(names, dtype=object),
        "country": np.array(country, dtype=object),
        "weight": weight,
        "size_rank": rank,
        "ticket_median_eur": ticket_median,
        "provider": provider,
        "switch_ts": switch_ts,
        "provider_after": after,
    }
