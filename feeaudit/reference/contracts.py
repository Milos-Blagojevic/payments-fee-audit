"""Provider contract versions and the interchange reference, read straight from YAML/CSV."""

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


@dataclass(frozen=True)
class ContractVersion:
    contract_id: str
    provider: str
    version: int
    effective_from: dt.date
    timezone: ZoneInfo
    rounding_mode: str
    terms: tuple[dict, ...]

    def terms_of(self, kind: str) -> list[dict]:
        return [t for t in self.terms if t["kind"] == kind]


@dataclass(frozen=True)
class Contract:
    """All versions of one provider's contract, ordered by `effective_from`."""

    provider: str
    timezone: ZoneInfo
    versions: tuple[ContractVersion, ...]

    def version_on(self, local_date: dt.date) -> ContractVersion:
        """Version whose [effective_from, next effective_from) contains the local date."""
        current = None
        for version in self.versions:
            if version.effective_from <= local_date:
                current = version
        if current is None:
            raise ValueError(f"no {self.provider} contract in force on {local_date}")
        return current

    def version_at(self, ts_utc: dt.datetime) -> ContractVersion:
        return self.version_on(ts_utc.astimezone(self.timezone).date())

    def month_of(self, ts_utc: dt.datetime) -> dt.date:
        """First day of the event's month in the contract timezone."""
        local = ts_utc.astimezone(self.timezone)
        return dt.date(local.year, local.month, 1)


def load_contract_version(path: Path) -> ContractVersion:
    doc = yaml.safe_load(Path(path).read_text())
    if doc["party"] != "provider":
        raise ValueError(f"{path}: not a provider contract")
    if doc["currency"] != "EUR":
        raise ValueError(f"{path}: provider fees must be billed in EUR")
    if doc["rounding"]["level"] != "transaction":
        raise ValueError(f"{path}: provider contracts round at transaction level")
    return ContractVersion(
        contract_id=doc["contract_id"],
        provider=doc["counterparty"],
        version=int(doc["version"]),
        effective_from=doc["effective_from"],
        timezone=ZoneInfo(doc["timezone"]),
        rounding_mode=doc["rounding"]["mode"],
        terms=tuple(doc["terms"]),
    )


def load_provider_contracts(directory: Path) -> dict[str, Contract]:
    """Read `contracts/providers/*.yml` into one `Contract` per provider."""
    by_provider: dict[str, list[ContractVersion]] = {}
    for path in sorted(Path(directory).glob("*.yml")):
        version = load_contract_version(path)
        by_provider.setdefault(version.provider, []).append(version)
    contracts = {}
    for provider, versions in by_provider.items():
        versions.sort(key=lambda v: v.effective_from)
        zones = {str(v.timezone) for v in versions}
        if len(zones) != 1:
            raise ValueError(f"{provider}: contract versions disagree on timezone {zones}")
        contracts[provider] = Contract(provider, versions[0].timezone, tuple(versions))
    return contracts


def load_interchange(path: Path) -> dict[tuple[str, str, str, str], tuple[int, int, int]]:
    """(reference, scheme, card_type, region) -> (interchange_bps, scheme_fee_bps, scheme_fee_fixed_minor)."""
    table = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            key = (row["reference"], row["card_scheme"], row["card_type"], row["card_region"])
            table[key] = (
                int(row["interchange_bps"]),
                int(row["scheme_fee_bps"]),
                int(row["scheme_fee_fixed_minor"]),
            )
    return table
