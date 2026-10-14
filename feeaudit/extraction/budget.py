"""LLM configuration, call cost and the spend ledger that caps total API spend (config/llm.yml).

Cost of a call = Σ tokens × price per million tokens / 1,000,000 over input, output, cache-write and cache-read
tokens, in exact `Decimal` USD. Before a call the guard adds the worst case of the next call (counted input
tokens plus `max_tokens` of output) to the ledger total and refuses when that would exceed the budget.
"""

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

CONFIG_PATH = Path("config/llm.yml")
MODEL_ENV = "FEEAUDIT_LLM_MODEL"
PRICE_KEYS = ("input", "output", "cache_write", "cache_read")
MILLION = Decimal(1_000_000)


class BudgetError(Exception):
    """The API must not be called: unverified or missing prices, or the call could exceed the budget."""


@dataclass(frozen=True)
class LlmConfig:
    default_model: str
    budget_usd: Decimal
    max_tokens: int
    effort: str
    prices_verified: bool
    prices: dict  # model id -> {price key: Decimal USD per million tokens}

    def model(self):
        """Model id: env FEEAUDIT_LLM_MODEL, else the configured default."""
        return os.environ.get(MODEL_ENV) or self.default_model

    def prices_for(self, model):
        """Prices of `model`; refuses to run on unverified or missing prices."""
        if not self.prices_verified:
            raise BudgetError(
                "config/llm.yml: prices_verified is false. Check every price against Anthropic's pricing page, "
                "then set prices_verified: true."
            )
        if model not in self.prices:
            raise BudgetError(f"config/llm.yml: no prices for model {model!r}; add them before calling it")
        return self.prices[model]


def load_config(path=CONFIG_PATH):
    raw = yaml.safe_load(Path(path).read_text())
    prices = {
        model: {key: Decimal(str(table[key])) for key in PRICE_KEYS}
        for model, table in raw["prices_usd_per_million_tokens"].items()
    }
    return LlmConfig(
        default_model=raw["default_model"],
        budget_usd=Decimal(str(raw["budget_usd"])),
        max_tokens=int(raw["max_tokens"]),
        effort=raw["effort"],
        prices_verified=raw["prices_verified"] is True,
        prices=prices,
    )


def call_cost(prices, input_tokens, output_tokens, cache_write_tokens=0, cache_read_tokens=0):
    """Exact USD cost of one call."""
    tokens = {"input": input_tokens, "output": output_tokens, "cache_write": cache_write_tokens, "cache_read": cache_read_tokens}
    return sum((Decimal(tokens[key]) * prices[key] for key in PRICE_KEYS), Decimal(0)) / MILLION


def usd(value):
    """Decimal USD as a plain string, e.g. '0.3215'."""
    return format(value.normalize(), "f") if value else "0"


def load_ledger(path):
    path = Path(path)
    if not path.exists():
        return {"total_usd": "0", "calls": []}
    return json.loads(path.read_text())


def spent(ledger):
    return sum((Decimal(call["cost_usd"]) for call in ledger["calls"]), Decimal(0))


def save_ledger(path, ledger):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["total_usd"] = usd(spent(ledger))
    path.write_text(json.dumps(ledger, indent=2) + "\n")


def check_budget(config, ledger, estimate):
    """Refuse when the ledger total plus the worst-case cost of the next call exceeds the budget."""
    total = spent(ledger)
    if total + estimate > config.budget_usd:
        raise BudgetError(
            f"budget guard: spent USD {usd(total)} + next call up to USD {usd(estimate)} would exceed the budget of "
            f"USD {usd(config.budget_usd)}; not calling the API"
        )
