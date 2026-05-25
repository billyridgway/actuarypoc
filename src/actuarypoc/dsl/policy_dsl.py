from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import yaml

RateType = Literal["guaranteed", "current", "illustrated"]


@dataclass
class Charge:
    name: str
    formula: str  # Placeholder expression until interpreter is built
    # Optional human-readable description of the charge; ignored by the engine
    # but useful for documentation / UI.
    description: str | None = None
    # Whether this charge is optional (e.g. rider) in the product design.
    optional: bool = False


@dataclass
class CreditRate:
    rate_type: RateType
    expression: str
    # Optional description field for documentation; ignored by the engine.
    description: str | None = None


@dataclass
class PolicyFormula:
    product_type: str
    charges: Sequence[Charge]
    credit_rates: Sequence[CreditRate]


def load_formula(path: str) -> PolicyFormula:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    charges = [Charge(**item) for item in data.get("charges", [])]
    rates = [CreditRate(**item) for item in data.get("credit_rates", [])]

    return PolicyFormula(
        product_type=data["product_type"],
        charges=charges,
        credit_rates=rates,
    )
