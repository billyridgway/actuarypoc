from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import yaml

RateType = Literal["guaranteed", "current", "illustrated"]


@dataclass
class Charge:
    name: str
    formula: str  # Placeholder expression until interpreter is built


@dataclass
class CreditRate:
    rate_type: RateType
    expression: str


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
