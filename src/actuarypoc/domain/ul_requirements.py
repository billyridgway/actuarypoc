from __future__ import annotations

"""UL requirement catalogue.

This module defines a small, product-line-aware catalogue of
requirements for universal life products. The goal is to keep the
semantics in one place and feed the generic requirement classifier
rather than hard-coding Promise-UL rules in the UI layer.

For now this mirrors the six core Promise-UL requirements:

- guaranteed credited rate
- death benefit option
- cash surrender value definition
- COI rate table
- surrender charge schedule
- policy / admin fees

Future iterations can extend this list or add more UL flavours without
changing the workspace surface.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class UlRequirementDefinition:
    requirement_id: str
    name: str
    category: str
    filed_requirement: str
    impact: str  # "high" | "medium" | "low"
    # ID of the corresponding field_evidence entry on UniversalLifeModel.
    field_evidence_id: str


def get_ul_requirement_definitions() -> List[UlRequirementDefinition]:
    """Return the core UL requirement definitions.

    These are intentionally Promise-UL-shaped for now but are expressed
    in generic UL terms so other UL products can share the same
    catalogue.
    """

    return [
        UlRequirementDefinition(
            requirement_id="guaranteed_credited_rate",
            name="Guaranteed credited rate",
            category="interest",
            filed_requirement="Policy credits interest at least at the guaranteed minimum rate.",
            impact="high",
            field_evidence_id="guaranteed_credited_rate",
        ),
        UlRequirementDefinition(
            requirement_id="death_benefit_option",
            name="Death benefit option",
            category="benefits",
            filed_requirement="Level death benefit equal to face amount (Option A).",
            impact="medium",
            field_evidence_id="death_benefit_option",
        ),
        UlRequirementDefinition(
            requirement_id="cash_surrender_value",
            name="Cash surrender value",
            category="benefits",
            filed_requirement="Cash surrender value equals policy value less any surrender charge.",
            impact="medium",
            field_evidence_id="cash_surrender_value",
        ),
        UlRequirementDefinition(
            requirement_id="coi_table",
            name="COI rate table",
            category="charges",
            filed_requirement="Cost of Insurance charges are determined using the filed COI rate tables.",
            impact="high",
            field_evidence_id="coi_rates",
        ),
        UlRequirementDefinition(
            requirement_id="surrender_schedule",
            name="Surrender charge schedule",
            category="charges",
            filed_requirement="Surrender charges follow the filed charge schedule by duration.",
            impact="medium",
            field_evidence_id="surrender_schedule",
        ),
        UlRequirementDefinition(
            requirement_id="policy_admin_fees",
            name="Policy / admin fees",
            category="charges",
            filed_requirement="Filed policy and admin fee schedule applies to the policy value.",
            impact="medium",
            field_evidence_id="policy_admin_fee",
        ),
    ]


__all__ = ["UlRequirementDefinition", "get_ul_requirement_definitions"]
