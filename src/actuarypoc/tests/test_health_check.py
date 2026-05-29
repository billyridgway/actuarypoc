from __future__ import annotations

import json

from actuarypoc.tools import health_check as hc
from actuarypoc.tools.health_check import CheckResult, HealthSummary, aggregate_status


def test_aggregate_status_all_healthy() -> None:
    checks = [
        CheckResult(name="kubectl_available", ok=True, critical=True, detail=""),
        CheckResult(name="pods_main", ok=True, critical=True, detail=""),
        CheckResult(name="projection_ui_health", ok=True, critical=False, detail=""),
    ]
    summary = aggregate_status(checks)
    assert summary.status == "HEALTHY"
    assert isinstance(summary, HealthSummary)
    d = summary.to_dict()
    assert d["status"] == "HEALTHY"
    assert len(d["checks"]) == 3


def test_aggregate_status_failed_on_critical() -> None:
    checks = [
        CheckResult(name="kubectl_available", ok=False, critical=True, detail=""),
        CheckResult(name="pods_main", ok=True, critical=True, detail=""),
        CheckResult(name="projection_ui_health", ok=False, critical=False, detail=""),
    ]
    summary = aggregate_status(checks)
    assert summary.status == "FAILED"


def test_aggregate_status_degraded_on_non_critical_failure() -> None:
    checks = [
        CheckResult(name="kubectl_available", ok=True, critical=True, detail=""),
        CheckResult(name="pods_main", ok=True, critical=True, detail=""),
        CheckResult(name="projection_ui_health", ok=False, critical=False, detail=""),
    ]
    summary = aggregate_status(checks)
    assert summary.status == "DEGRADED"


def test_aggregate_status_unknown_when_inconclusive_only() -> None:
    checks = [
        CheckResult(name="kubectl_available", ok=False, critical=True, detail="kubectl not found", inconclusive=True),
        CheckResult(name="minio_health", ok=False, critical=False, detail="Missing MINIO_ENDPOINT", inconclusive=True),
    ]
    summary = aggregate_status(checks)
    assert summary.status == "UNKNOWN"


def test_healthsummary_to_dict_json_roundtrip() -> None:
    checks = [CheckResult(name="example", ok=True, critical=False, detail="foo")]
    summary = aggregate_status(checks)
    data = summary.to_dict()
    encoded = json.dumps(data)
    decoded = json.loads(encoded)
    assert decoded["status"] == summary.status
    assert decoded["checks"][0]["name"] == "example"


def test_check_pods_ignores_succeeded_job_pods(monkeypatch) -> None:
    # Pod in Succeeded phase should be ignored for readiness.
    pods_json = {
        "items": [
            {
                "metadata": {"name": "job-pod-succeeded"},
                "status": {
                    "phase": "Succeeded",
                    "containerStatuses": [
                        {"name": "c", "ready": False},
                    ],
                },
            }
        ]
    }

    def fake_run_kubectl(args, kubeconfig):  # type: ignore[override]
        return True, json.dumps(pods_json), ""

    monkeypatch.setattr(hc, "_run_kubectl", fake_run_kubectl)

    result = hc._check_pods("ns", kubeconfig=None, label="pods-main")
    assert result.ok is True
    assert "Pods not ready" not in result.detail


def test_check_pods_ignores_failed_job_pods_for_readiness(monkeypatch) -> None:
    # Failed pods should not affect namespace readiness; jobs_failed covers them.
    pods_json = {
        "items": [
            {
                "metadata": {"name": "job-pod-failed"},
                "status": {
                    "phase": "Failed",
                    "containerStatuses": [
                        {"name": "c", "ready": False},
                    ],
                },
            }
        ]
    }

    def fake_run_kubectl(args, kubeconfig):  # type: ignore[override]
        return True, json.dumps(pods_json), ""

    monkeypatch.setattr(hc, "_run_kubectl", fake_run_kubectl)

    result = hc._check_pods("ns", kubeconfig=None, label="pods-main")
    assert result.ok is True


def test_check_pods_running_unready_fails(monkeypatch) -> None:
    pods_json = {
        "items": [
            {
                "metadata": {"name": "running-unready"},
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {"name": "c", "ready": False},
                    ],
                },
            }
        ]
    }

    def fake_run_kubectl(args, kubeconfig):  # type: ignore[override]
        return True, json.dumps(pods_json), ""

    monkeypatch.setattr(hc, "_run_kubectl", fake_run_kubectl)

    result = hc._check_pods("ns", kubeconfig=None, label="pods-main")
    assert result.ok is False
    assert "running-unready" in result.detail


def test_check_pods_running_all_ready_passes(monkeypatch) -> None:
    pods_json = {
        "items": [
            {
                "metadata": {"name": "running-ready"},
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {"name": "c", "ready": True},
                    ],
                },
            }
        ]
    }

    def fake_run_kubectl(args, kubeconfig):  # type: ignore[override]
        return True, json.dumps(pods_json), ""

    monkeypatch.setattr(hc, "_run_kubectl", fake_run_kubectl)

    result = hc._check_pods("ns", kubeconfig=None, label="pods-main")
    assert result.ok is True
    assert "running-ready" not in result.detail
