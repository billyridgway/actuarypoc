"""Synthetic-agent reliability: bounded model calls + truthful deterministic fallback.

The synthetic COI / surrender agents ask a model for a small parameter set.
In production that model is a local endpoint behind the Roost facade, where
a cold or contended call can run for minutes; the previous code used the
OpenAI SDK defaults (~600s timeout, 2 retries) and raised on any failure,
so the "Generate synthetic ..." buttons simply never answered.

These tests pin the fix: the client is constructed with a bounded timeout
and no retries, and ANY model failure (timeout, connection error, invalid
JSON, unusable parameters, missing API key) returns a preview built from
the module's DEFAULT_PARAMETERS — truthfully labelled as a deterministic
fallback in the parameters, the preview, the built rows' provenance, and
what the accept endpoints persist.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

from actuarypoc.agents import synthetic_coi_ai, synthetic_surrender_ai
from actuarypoc.agents.synthetic_coi_ai import propose_synthetic_coi_parameters, synthetic_coi_preview
from actuarypoc.agents.synthetic_surrender_ai import (
    propose_synthetic_surrender_parameters,
    synthetic_surrender_preview,
)
from actuarypoc.domain.projection_ledger import _kind_from_source
from actuarypoc.ui import server


class _FakeCompletions:
    def __init__(self, behavior):
        self._behavior = behavior

    def create(self, **_kwargs):
        kind, payload = self._behavior
        if kind == "timeout":
            raise APITimeoutError(httpx.Request("POST", "http://localhost"))
        if kind == "connection":
            raise APIConnectionError(request=httpx.Request("POST", "http://localhost"))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))],
        )


class _FakeOpenAI:
    """Stands in for openai.OpenAI; records every construction."""

    instances: list = []
    behavior = ("ok", "{}")

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        type(self).instances.append(self)
        self.chat = SimpleNamespace(completions=_FakeCompletions(type(self).behavior))


@pytest.fixture(autouse=True)
def _fake_openai(monkeypatch):
    _FakeOpenAI.instances = []
    _FakeOpenAI.behavior = ("ok", "{}")
    monkeypatch.setattr(synthetic_surrender_ai, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(synthetic_coi_ai, "OpenAI", _FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    monkeypatch.delenv("SYNTHETIC_AGENT_TIMEOUT_S", raising=False)
    return _FakeOpenAI


SURRENDER_MODEL_JSON = json.dumps({
    "initial_charge_percent_account_value": 0.12,
    "terminal_charge_percent_account_value": 0.02,
    "period_years": 10,
    "curve_shape": "front_loaded",
    "rationale": "Model-proposed shape",
})

COI_MODEL_JSON = json.dumps({
    "base_rate_per_1000_annual": 0.40,
    "reference_age": 40,
    "annual_age_growth": 0.08,
    "male_multiplier": 1.10,
    "tobacco_multiplier": 2.00,
    "risk_class_multipliers": {"Preferred": 0.8, "Standard": 1.0},
    "minimum_rate": 0.05,
    "maximum_rate": 50.0,
    "rationale": "Model-proposed COI parameters",
})

RISK_CLASSES = ["Preferred", "Standard"]


# ---------------------------------------------------------------------------
# Surrender agent
# ---------------------------------------------------------------------------


def test_surrender_timeout_returns_labelled_deterministic_fallback(_fake_openai):
    _fake_openai.behavior = ("timeout", None)

    parameters = propose_synthetic_surrender_parameters(product_code="UL-1", product_context="ctx")

    assert parameters["agentFallback"] is True
    assert parameters["model"] == synthetic_surrender_ai.FALLBACK_MODEL_LABEL
    assert "unavailable" in parameters["model"].lower()
    # The defaults are used, untouched.
    assert parameters["initial_charge_percent_account_value"] == synthetic_surrender_ai.DEFAULT_PARAMETERS["initial_charge_percent_account_value"]
    assert parameters["terminal_charge_percent_account_value"] == synthetic_surrender_ai.DEFAULT_PARAMETERS["terminal_charge_percent_account_value"]
    assert parameters["period_years"] == synthetic_surrender_ai.DEFAULT_PARAMETERS["period_years"]
    assert parameters["curve_shape"] == synthetic_surrender_ai.DEFAULT_PARAMETERS["curve_shape"]
    assert "unavailable" in parameters["rationale"].lower()
    assert "default" in parameters["rationale"].lower()

    preview = synthetic_surrender_preview(parameters=parameters)
    assert preview["agentFallback"] is True
    assert preview["rowCount"] == synthetic_surrender_ai.DEFAULT_PARAMETERS["period_years"]
    assert preview["rows"][0]["charge"] == 0.10
    assert preview["rows"][-1]["charge"] == 0.0
    assert all(row["provenance"]["sourceType"] == "deterministic_fallback" for row in preview["rows"])
    assert all("AI-generated" not in row["provenance"]["filename"] for row in preview["rows"])
    assert "unavailable" in preview["disclaimer"].lower()


def test_surrender_invalid_json_returns_fallback(_fake_openai):
    _fake_openai.behavior = ("ok", "this is not json {")

    parameters = propose_synthetic_surrender_parameters(product_code="UL-1", product_context="ctx")

    assert parameters["agentFallback"] is True
    assert parameters["period_years"] == synthetic_surrender_ai.DEFAULT_PARAMETERS["period_years"]


def test_surrender_missing_api_key_returns_fallback_without_calling_model(_fake_openai, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")

    parameters = propose_synthetic_surrender_parameters(product_code="UL-1", product_context="ctx")

    assert parameters["agentFallback"] is True
    assert _fake_openai.instances == []


def test_surrender_client_is_bounded_and_does_not_retry(_fake_openai, monkeypatch):
    _fake_openai.behavior = ("ok", SURRENDER_MODEL_JSON)

    propose_synthetic_surrender_parameters(product_code="UL-1", product_context="ctx")

    assert len(_fake_openai.instances) == 1
    kwargs = _fake_openai.instances[0].kwargs
    assert kwargs["timeout"] == 45.0
    assert kwargs["max_retries"] == 0

    monkeypatch.setenv("SYNTHETIC_AGENT_TIMEOUT_S", "7")
    propose_synthetic_surrender_parameters(product_code="UL-1", product_context="ctx")
    assert _fake_openai.instances[-1].kwargs["timeout"] == 7.0


def test_surrender_success_path_is_unchanged(_fake_openai):
    _fake_openai.behavior = ("ok", SURRENDER_MODEL_JSON)

    parameters = propose_synthetic_surrender_parameters(
        product_code="UL-1", product_context="ctx", model="unit-test-model",
    )

    assert parameters["model"] == "unit-test-model"
    assert not parameters.get("agentFallback")
    assert parameters["initial_charge_percent_account_value"] == 0.12
    assert parameters["terminal_charge_percent_account_value"] == 0.02
    assert parameters["period_years"] == 10
    assert parameters["curve_shape"] == "front_loaded"
    assert parameters["rationale"] == "Model-proposed shape"

    preview = synthetic_surrender_preview(parameters=parameters)
    assert preview["agentFallback"] is False
    assert all(row["provenance"]["sourceType"] == "ai_synthetic" for row in preview["rows"])
    assert "AI-generated" in preview["disclaimer"]


# ---------------------------------------------------------------------------
# COI agent
# ---------------------------------------------------------------------------


def test_coi_timeout_returns_labelled_deterministic_fallback(_fake_openai):
    _fake_openai.behavior = ("timeout", None)

    parameters = propose_synthetic_coi_parameters(
        product_code="UL-1", product_context="ctx", risk_classes=RISK_CLASSES,
    )

    assert parameters["agentFallback"] is True
    assert parameters["model"] == synthetic_coi_ai.FALLBACK_MODEL_LABEL
    assert parameters["base_rate_per_1000_annual"] == synthetic_coi_ai.DEFAULT_PARAMETERS["base_rate_per_1000_annual"]
    assert parameters["risk_class_multipliers"] == {"Preferred": 0.80, "Standard": 1.00}
    assert "unavailable" in parameters["rationale"].lower()

    preview = synthetic_coi_preview(parameters=parameters, risk_classes=RISK_CLASSES)
    assert preview["agentFallback"] is True
    assert preview["rowCount"] > 0
    assert all(row["provenance"]["sourceType"] == "deterministic_fallback" for row in preview["rows"])
    assert "unavailable" in preview["disclaimer"].lower()


def test_coi_connection_error_returns_fallback(_fake_openai):
    _fake_openai.behavior = ("connection", None)

    parameters = propose_synthetic_coi_parameters(
        product_code="UL-1", product_context="ctx", risk_classes=RISK_CLASSES,
    )

    assert parameters["agentFallback"] is True


def test_coi_unusable_model_parameters_return_fallback(_fake_openai):
    bad = json.loads(COI_MODEL_JSON)
    bad["annual_age_growth"] = 0.9  # outside the validated bounds
    _fake_openai.behavior = ("ok", json.dumps(bad))

    parameters = propose_synthetic_coi_parameters(
        product_code="UL-1", product_context="ctx", risk_classes=RISK_CLASSES,
    )

    assert parameters["agentFallback"] is True
    assert parameters["annual_age_growth"] == synthetic_coi_ai.DEFAULT_PARAMETERS["annual_age_growth"]


def test_coi_missing_api_key_returns_fallback_without_calling_model(_fake_openai, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")

    parameters = propose_synthetic_coi_parameters(
        product_code="UL-1", product_context="ctx", risk_classes=RISK_CLASSES,
    )

    assert parameters["agentFallback"] is True
    assert _fake_openai.instances == []


def test_coi_client_is_bounded_and_success_path_is_unchanged(_fake_openai):
    _fake_openai.behavior = ("ok", COI_MODEL_JSON)

    parameters = propose_synthetic_coi_parameters(
        product_code="UL-1", product_context="ctx", risk_classes=RISK_CLASSES, model="unit-test-model",
    )

    kwargs = _fake_openai.instances[0].kwargs
    assert kwargs["timeout"] == 45.0
    assert kwargs["max_retries"] == 0
    assert parameters["model"] == "unit-test-model"
    assert not parameters.get("agentFallback")
    assert parameters["base_rate_per_1000_annual"] == 0.40

    preview = synthetic_coi_preview(parameters=parameters, risk_classes=RISK_CLASSES)
    assert preview["agentFallback"] is False
    assert all(row["provenance"]["sourceType"] == "ai_synthetic" for row in preview["rows"])


# ---------------------------------------------------------------------------
# Accept path: persisted provenance must tell the truth
# ---------------------------------------------------------------------------


def _stub_workspace_store(monkeypatch, artifact):
    monkeypatch.setattr(server, "get_workspace", lambda workspace_id: {"id": workspace_id})
    monkeypatch.setattr(server, "load_workspace_executable_mechanics", lambda workspace_id: artifact)
    monkeypatch.setattr(server, "store_workspace_executable_mechanics", lambda workspace_id, value: "key")


def test_accept_persists_fallback_surrender_as_deterministic_not_ai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    parameters = propose_synthetic_surrender_parameters(product_code="UL-1", product_context="ctx")
    artifact = {"usable": {}, "status": {}, "warnings": []}
    _stub_workspace_store(monkeypatch, artifact)

    response = server.api_accept_synthetic_surrender(
        "workspace-1",
        server.SyntheticCoiAcceptRequest(parameters=parameters, model=parameters["model"]),
    )

    assert response["accepted"] is True
    record = artifact["synthetic"]["surrender"]
    assert record["sourceType"] == "deterministic_fallback"
    assert record["agentFallback"] is True
    assert record["model"] == synthetic_surrender_ai.FALLBACK_MODEL_LABEL
    assert all(
        row["provenance"]["sourceType"] == "deterministic_fallback"
        for row in artifact["usable"]["surrender"]
    )


def test_accept_persists_model_surrender_as_ai_synthetic(monkeypatch):
    parameters = {
        "initial_charge_percent_account_value": 0.12,
        "terminal_charge_percent_account_value": 0.0,
        "period_years": 10,
        "curve_shape": "linear",
        "rationale": "Unit-test schedule",
    }
    artifact = {"usable": {}, "status": {}, "warnings": []}
    _stub_workspace_store(monkeypatch, artifact)

    server.api_accept_synthetic_surrender(
        "workspace-1",
        server.SyntheticCoiAcceptRequest(parameters=parameters, model="test-model"),
    )

    record = artifact["synthetic"]["surrender"]
    assert record["sourceType"] == "ai_synthetic"
    assert record["agentFallback"] is False
    assert all(row["provenance"]["sourceType"] == "ai_synthetic" for row in artifact["usable"]["surrender"])


def test_accept_persists_fallback_coi_as_deterministic_not_ai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    parameters = propose_synthetic_coi_parameters(
        product_code="UL-1", product_context="ctx", risk_classes=RISK_CLASSES,
    )
    artifact = {"usable": {}, "status": {}, "warnings": []}
    _stub_workspace_store(monkeypatch, artifact)
    monkeypatch.setattr(server, "_workspace_synthetic_coi_context", lambda ws: ("ctx", RISK_CLASSES))

    response = server.api_accept_synthetic_coi(
        "workspace-1",
        server.SyntheticCoiAcceptRequest(parameters=parameters, model=parameters["model"]),
    )

    assert response["accepted"] is True
    record = artifact["synthetic"]["coi"]
    assert record["sourceType"] == "deterministic_fallback"
    assert record["agentFallback"] is True
    assert all(
        row["provenance"]["sourceType"] == "deterministic_fallback"
        for row in artifact["usable"]["coi"]
    )


def test_ledger_basis_treats_fallback_rows_as_synthetic():
    assert _kind_from_source({"sourceType": "deterministic_fallback"}) == "synthetic"
    assert _kind_from_source({"sourceType": "ai_synthetic"}) == "synthetic"
