"""`metrics.lock.yml`: the version and fingerprint of every metric (A51).

`lock --check` (in `make all`) fails when a definition changed without a version bump, when a version was bumped
but the lock not updated, or when a metric is missing from or extra in the lock. `lock --update` rewrites it, and
only accepts a changed definition whose version is exactly the locked version + 1.
"""

from pathlib import Path

import yaml

from metrics_mcp.catalog import Catalog

HEADER = (
    "# Version and fingerprint of every metric of dbt/models/semantic/ (A50, A51). Written by\n"
    "# `python -m metrics_mcp lock --update` after a version bump; checked by `lock --check` in `make all`.\n"
)
UPDATE = "run `python -m metrics_mcp lock --update`"


def read(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return (yaml.safe_load(path.read_text()) or {}).get("metrics") or {}


def write(path: Path, entries: dict[str, dict]) -> None:
    body = yaml.safe_dump({"metrics": dict(sorted(entries.items()))}, sort_keys=False, allow_unicode=True)
    path.write_text(HEADER + body)


def problems(catalog: Catalog, locked: dict[str, dict]) -> tuple[list[str], list[str]]:
    """(problems `lock --update` fixes, problems it refuses to fix) of the catalog against the lock."""
    fixable, blocking = [], list(catalog.problems)
    for metric_id in sorted(set(catalog.metrics) | set(locked)):
        metric, entry = catalog.metrics.get(metric_id), locked.get(metric_id)
        if metric is None:
            fixable.append(f"{metric_id} is in metrics.lock.yml but no metric defines it: {UPDATE}")
        elif entry is None:
            if metric.version == 1:
                fixable.append(f"{metric_id} ({metric.name}) is missing from metrics.lock.yml: {UPDATE}")
            else:
                blocking.append(f"{metric_id} ({metric.name}) is new: start meta.version at 1, not {metric.version}")
        elif metric.version == entry["version"]:
            if metric.fingerprint != entry["fingerprint"]:
                blocking.append(
                    f"{metric_id} ({metric.name}) definition changed (fingerprint {entry['fingerprint']} -> "
                    f"{metric.fingerprint}) but meta.version is still {metric.version}: bump the version to "
                    f"{metric.version + 1} in dbt/models/semantic/_semantic.yml, rebuild, then {UPDATE}"
                )
        elif metric.version == entry["version"] + 1:
            fixable.append(f"{metric_id} ({metric.name}) version bumped to {metric.version} but metrics.lock.yml has "
                           f"{entry['version']}: {UPDATE}")
        else:
            blocking.append(f"{metric_id} ({metric.name}) meta.version is {metric.version} and metrics.lock.yml has "
                            f"{entry['version']}: the next version must be exactly {entry['version'] + 1}")
    return fixable, blocking


def check(catalog: Catalog, path: Path) -> list[str]:
    fixable, blocking = problems(catalog, read(path))
    return blocking + fixable


def update(catalog: Catalog, path: Path) -> list[str]:
    """Rewrite the lock from the catalog; returns the blocking problems instead when there are any."""
    _, blocking = problems(catalog, read(path))
    if blocking:
        return blocking
    write(path, {m.metric_id: {"name": m.name, "version": m.version, "fingerprint": m.fingerprint}
                 for m in catalog.metrics.values()})
    return []
