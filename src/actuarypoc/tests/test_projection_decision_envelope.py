from __future__ import annotations

import sys
import types

sys.modules.setdefault("psycopg", types.SimpleNamespace())

from actuarypoc.ui.server import _build_projection_decision


def test_projection_decision_blocks_when_canonical_state_is_not_eligible() -> None:
    readiness = {
        "projectionEligible": False,
        "projectionTrustLevel": "draft_illustration",
        "projectionBlockers": [
            {
                "requirementId": "coi_table",
                "category": "missingInformation",
                "reason": "Applicable requirement input is absent or not ready.",
            }
        ],
    }

    decision = _build_projection_decision(readiness, illustration={"years": [1]})

    assert decision["status"] == "blocked"
    assert decision["eligible"] is False
    assert decision["projection"] is None
    assert decision["blockers"] == readiness["projectionBlockers"]
    assert decision["trustLevel"] == "draft_illustration"


def test_projection_decision_returns_projection_only_when_eligible() -> None:
    illustration = {"years": [1], "cash_values": [10.0], "death_benefits": [100.0]}
    readiness = {
        "projectionEligible": True,
        "projectionTrustLevel": "filed_rate_ready",
        "projectionBlockers": [],
    }

    decision = _build_projection_decision(readiness, illustration=illustration)

    assert decision["status"] == "projected"
    assert decision["eligible"] is True
    assert decision["blockers"] == []
    assert decision["projection"] == illustration
    assert decision["trustLevel"] == "filed_rate_ready"
