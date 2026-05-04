from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from actuarypoc.dsl.policy_dsl import CreditRate, PolicyFormula


@dataclass(slots=True)
class ProjectionResult:
    years: List[int]
    cash_values: List[float]
    death_benefits: List[float]


class ProjectionEngine:
    def __init__(self, formula: PolicyFormula) -> None:
        self.formula = formula

    def project(self, policy_record: Dict[str, float | str], horizon: int = 20) -> ProjectionResult:
        premium = float(policy_record.get("premium", 0))
        face_amount = float(policy_record.get("face_amount", 0))
        rate = float(policy_record.get("interest_rate", 0.04))

        cash_values: List[float] = []
        death_benefits: List[float] = []
        current_value = premium

        for year in range(1, horizon + 1):
            current_value = current_value * (1 + rate) + premium
            cash_values.append(round(current_value, 2))
            death_benefits.append(round(face_amount + 0.05 * current_value, 2))

        return ProjectionResult(
            years=list(range(1, horizon + 1)),
            cash_values=cash_values,
            death_benefits=death_benefits,
        )
