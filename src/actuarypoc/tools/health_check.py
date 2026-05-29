from __future__ import annotations

"""Lightweight project health CLI for the Insurance Illustration Platform.

This module performs a small set of safe, read-only checks to answer the
question:

    "Is the insurance illustration platform healthy right now?"

It follows the design in docs/workflows/project-health.md and is intended as a
thin first slice. It:

- relies on `kubectl` being available in PATH
- inspects workloads in the k3s cluster
- checks core namespaces and Deployments
- summarizes IllustrationProject phases
- counts failed Jobs
- optionally checks the projection UI `/health` endpoint
- optionally checks MinIO reachability using the existing MinIO client

It does **not**:

- read or print secrets/DSNs
- dump raw PAS exports or projection JSON
- modify any cluster state.

Run via:

    python -m actuarypoc.tools.health_check [OPTIONS]

or import and call `run_health_check()` from Python.
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # optional import; MinIO health is best-effort only
    from actuarypoc.storage.minio_client import get_minio_client, get_bucket_name
except Exception:  # pragma: no cover - defensive
    get_minio_client = None  # type: ignore[assignment]
    get_bucket_name = None  # type: ignore[assignment]

import urllib.error
import urllib.request


@dataclass
class CheckResult:
    name: str
    ok: bool
    critical: bool
    detail: str = ""
    # When True, this check could not reach the platform at all due to
    # missing local tooling or configuration (e.g. kubectl not found,
    # kubeconfig missing, MinIO env vars not set). These contribute to an
    # overall UNKNOWN status when no real platform failures are present.
    inconclusive: bool = False


@dataclass
class HealthSummary:
    status: str
    checks: List[CheckResult]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "checks": [asdict(c) for c in self.checks],
        }


def _run_kubectl(args: List[str], kubeconfig: Optional[str]) -> Tuple[bool, str, str]:
    """Run a kubectl command and return (ok, stdout, stderr).

    Does not raise on failure; callers should inspect the boolean.
    """

    cmd = ["kubectl"] + args
    env = None
    if kubeconfig:
        # Preserve the existing environment (especially PATH) while
        # injecting/overriding KUBECONFIG. Replacing env entirely here
        # would hide kubectl from PATH even when it is installed.
        env = dict(os.environ)
        env["KUBECONFIG"] = kubeconfig

    try:
        proc = subprocess.run(
            cmd,
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        return False, "", "kubectl not found in PATH"
    except Exception as exc:  # pragma: no cover - defensive
        return False, "", f"kubectl error: {exc}"

    ok = proc.returncode == 0
    return ok, proc.stdout, proc.stderr


def _check_kubectl_available(kubeconfig: Optional[str]) -> CheckResult:
    # Treat a missing kubeconfig path as a local configuration issue rather
    # than a platform failure.
    if kubeconfig is not None and not Path(kubeconfig).exists():
        return CheckResult(
            name="kubectl_available",
            ok=False,
            critical=True,
            detail=f"kubeconfig {kubeconfig} not found",
            inconclusive=True,
        )

    ok, _, err = _run_kubectl(["version", "--client"], kubeconfig)
    if not ok:
        detail = f"kubectl not available or failed: {err.strip()}"
        inconclusive = "kubectl not found in PATH" in err
        return CheckResult(
            name="kubectl_available",
            ok=False,
            critical=True,
            detail=detail,
            inconclusive=inconclusive,
        )
    return CheckResult(name="kubectl_available", ok=True, critical=True, detail="kubectl client OK")


def _check_pods(namespace: str, kubeconfig: Optional[str], label: str) -> CheckResult:
    ok, out, err = _run_kubectl(["get", "pods", "-n", namespace, "-o", "json"], kubeconfig)
    if not ok:
        inconclusive = "kubectl not found in PATH" in err
        return CheckResult(
            name=f"pods_{namespace}",
            ok=False,
            critical=True,
            detail=f"Failed to list pods in {namespace}: {err.strip()}",
            inconclusive=inconclusive,
        )

    try:
        data = json.loads(out or "{}")
    except json.JSONDecodeError:
        return CheckResult(
            name=f"pods_{namespace}",
            ok=False,
            critical=True,
            detail=f"Invalid JSON from kubectl get pods -n {namespace}",
        )

    total = 0
    not_ready: List[str] = []
    for item in data.get("items", []):
        status = item.get("status", {}) or {}
        phase = status.get("phase")

        # Ignore pods that are already in a terminal phase. Succeeded/Failed
        # Job pods should not cause the namespace readiness check itself to
        # fail; failed Jobs are surfaced separately via jobs_failed.
        if phase in {"Succeeded", "Failed"}:
            continue

        total += 1
        name = item.get("metadata", {}).get("name", "<unknown>")
        cs = status.get("containerStatuses", []) or []
        if not cs:
            not_ready.append(name)
            continue
        if not all(c.get("ready") for c in cs):
            not_ready.append(name)

    if not_ready:
        return CheckResult(
            name=f"pods_{namespace}",
            ok=False,
            critical=True,
            detail=f"Pods not ready in {namespace}: {', '.join(not_ready)}",
        )

    return CheckResult(
        name=f"pods_{namespace}",
        ok=True,
        critical=True,
        detail=f"All {total} pods Ready in {namespace}",
    )


def _check_operator_deployment(namespace: str, kubeconfig: Optional[str]) -> CheckResult:
    ok, out, err = _run_kubectl([
        "get",
        "deploy",
        "illustration-operator",
        "-n",
        namespace,
        "-o",
        "json",
    ], kubeconfig)
    if not ok:
        inconclusive = "kubectl not found in PATH" in err
        return CheckResult(
            name="illustration_operator_deploy",
            ok=False,
            critical=True,
            detail=f"Failed to get illustration-operator deployment: {err.strip()}",
            inconclusive=inconclusive,
        )

    try:
        data = json.loads(out or "{}")
    except json.JSONDecodeError:
        return CheckResult(
            name="illustration_operator_deploy",
            ok=False,
            critical=True,
            detail="Invalid JSON from kubectl get deploy illustration-operator",
        )

    desired = data.get("spec", {}).get("replicas", 0)
    ready = data.get("status", {}).get("readyReplicas", 0)
    if desired and ready < desired:
        return CheckResult(
            name="illustration_operator_deploy",
            ok=False,
            critical=True,
            detail=f"illustration-operator not fully ready (desired={desired}, ready={ready})",
        )

    return CheckResult(
        name="illustration_operator_deploy",
        ok=True,
        critical=True,
        detail=f"illustration-operator Ready (replicas={ready})",
    )


def _check_crd_exists(kubeconfig: Optional[str]) -> CheckResult:
    ok, _, err = _run_kubectl([
        "get",
        "crd",
        "illustrationprojects.illustrations.poc",
        "-o",
        "json",
    ], kubeconfig)
    if not ok:
        inconclusive = "kubectl not found in PATH" in err
        return CheckResult(
            name="illustrationproject_crd",
            ok=False,
            critical=True,
            detail=f"CRD illustrationprojects.illustrations.poc missing or unreadable: {err.strip()}",
            inconclusive=inconclusive,
        )
    return CheckResult(
        name="illustrationproject_crd",
        ok=True,
        critical=True,
        detail="CRD illustrationprojects.illustrations.poc present",
    )


def _check_ilproj_phases(namespace: str, kubeconfig: Optional[str]) -> CheckResult:
    ok, out, err = _run_kubectl([
        "get",
        "illustrationprojects.illustrations.poc",
        "-n",
        namespace,
        "-o",
        "json",
    ], kubeconfig)
    if not ok:
        # Non-critical: platform can still be healthy with zero projects. If
        # kubectl itself is missing, treat as inconclusive rather than
        # signalling a degraded platform.
        inconclusive = "kubectl not found in PATH" in err
        return CheckResult(
            name="illustrationproject_phases",
            ok=not inconclusive,
            critical=False,
            detail=f"Could not list IllustrationProjects (namespace={namespace}): {err.strip()}",
            inconclusive=inconclusive,
        )

    try:
        data = json.loads(out or "{}")
    except json.JSONDecodeError:
        return CheckResult(
            name="illustrationproject_phases",
            ok=False,
            critical=False,
            detail="Invalid JSON from kubectl get illustrationprojects",
        )

    counts: Dict[str, int] = {}
    for item in data.get("items", []):
        phase = (item.get("status", {}) or {}).get("phase") or "Unknown"
        counts[phase] = counts.get(phase, 0) + 1

    # Consider many Failed projects as degraded
    failed = counts.get("Failed", 0)
    if failed:
        return CheckResult(
            name="illustrationproject_phases",
            ok=False,
            critical=False,
            detail=f"IllustrationProjects by phase: {counts} (Failed={failed})",
        )

    return CheckResult(
        name="illustrationproject_phases",
        ok=True,
        critical=False,
        detail=f"IllustrationProjects by phase: {counts or 'none'}",
    )


def _check_failed_jobs(namespace: str, kubeconfig: Optional[str]) -> CheckResult:
    ok, out, err = _run_kubectl(["get", "jobs", "-n", namespace, "-o", "json"], kubeconfig)
    if not ok:
        inconclusive = "kubectl not found in PATH" in err
        return CheckResult(
            name="jobs_failed",
            ok=not inconclusive,
            critical=False,
            detail=f"Could not list Jobs in {namespace}: {err.strip()}",
            inconclusive=inconclusive,
        )

    try:
        data = json.loads(out or "{}")
    except json.JSONDecodeError:
        return CheckResult(
            name="jobs_failed",
            ok=False,
            critical=False,
            detail=f"Invalid JSON from kubectl get jobs -n {namespace}",
        )

    failed_jobs: List[str] = []
    for item in data.get("items", []):
        name = item.get("metadata", {}).get("name", "<unknown>")
        status = item.get("status", {}) or {}
        if status.get("failed", 0):
            failed_jobs.append(name)
        else:
            for cond in status.get("conditions", []) or []:
                if cond.get("type") == "Failed" and cond.get("status") == "True":
                    failed_jobs.append(name)
                    break

    if failed_jobs:
        return CheckResult(
            name="jobs_failed",
            ok=False,
            critical=False,
            detail=f"Failed Jobs in {namespace}: {', '.join(failed_jobs)}",
        )

    return CheckResult(
        name="jobs_failed",
        ok=True,
        critical=False,
        detail=f"No failed Jobs in {namespace}",
    )


def _check_projection_ui_health(ui_url: Optional[str]) -> CheckResult:
    if not ui_url:
        return CheckResult(
            name="projection_ui_health",
            ok=True,
            critical=False,
            detail="UI health URL not configured; skipping",
        )

    try:
        with urllib.request.urlopen(ui_url, timeout=5) as resp:
            code = resp.getcode()
            body = resp.read(256).decode("utf-8", errors="ignore")
    except urllib.error.URLError as exc:
        return CheckResult(
            name="projection_ui_health",
            ok=False,
            critical=False,
            detail=f"UI health check failed: {exc}",
        )

    if code != 200:
        return CheckResult(
            name="projection_ui_health",
            ok=False,
            critical=False,
            detail=f"UI health returned HTTP {code}",
        )

    # Avoid echoing full body; just confirm we saw something.
    return CheckResult(
        name="projection_ui_health",
        ok=True,
        critical=False,
        detail="UI /health responded with HTTP 200",
    )


def _check_minio_best_effort() -> CheckResult:
    if get_minio_client is None or get_bucket_name is None:
        return CheckResult(
            name="minio_health",
            ok=True,
            critical=False,
            detail="MinIO client not available in this environment; skipping",
        )

    try:
        client = get_minio_client()
        bucket = get_bucket_name()
        # Best-effort small operation: list at most one object.
        found_any = False
        for _ in client.list_objects(bucket, max_keys=1):  # type: ignore[attr-defined]
            found_any = True
            break
    except Exception as exc:  # pragma: no cover - network/MinIO dependent
        detail = str(exc)
        inconclusive = "Missing required environment variable: MINIO_ENDPOINT" in detail
        return CheckResult(
            name="minio_health",
            ok=not inconclusive,
            critical=False,
            detail=f"MinIO check failed: {detail}",
            inconclusive=inconclusive,
        )

    if found_any:
        return CheckResult(
            name="minio_health",
            ok=True,
            critical=False,
            detail="MinIO reachable and bucket accessible (saw at least one object or empty bucket)",
        )
    return CheckResult(
        name="minio_health",
        ok=True,
        critical=False,
        detail="MinIO reachable and bucket accessible (no objects listed)",
    )


def aggregate_status(checks: List[CheckResult]) -> HealthSummary:
    """Aggregate individual check results into an overall HealthSummary.

    Rules:
    - If any *critical* check fails (ok is False and not inconclusive)
      → FAILED.
    - Else if any non-critical check fails (ok is False and not
      inconclusive) → DEGRADED.
    - Else if at least one check is inconclusive (e.g. kubectl missing,
      kubeconfig not found, MinIO env vars missing) and there are no real
      failures → UNKNOWN.
    - Else → HEALTHY.
    """

    overall = "HEALTHY"

    # 1) Any real critical failure → FAILED
    for c in checks:
        if not c.ok and c.critical and not c.inconclusive:
            overall = "FAILED"
            break
    else:
        # 2) Any real non-critical failure → DEGRADED
        if any((not c.ok) and (not c.critical) and (not c.inconclusive) for c in checks):
            overall = "DEGRADED"
        # 3) No real failures but at least one inconclusive → UNKNOWN
        elif any(c.inconclusive for c in checks):
            overall = "UNKNOWN"

    return HealthSummary(status=overall, checks=checks)


def run_health_check(
    kubeconfig: Optional[str],
    namespace: str,
    minio_namespace: str,
    ui_url: Optional[str],
) -> HealthSummary:
    """Run a series of safe health checks and return a HealthSummary.

    Network/cluster-dependent checks are best-effort and should not raise.
    """

    checks: List[CheckResult] = []

    # 1) kubectl availability
    checks.append(_check_kubectl_available(kubeconfig))

    # 2) pods in main and minio namespaces
    checks.append(_check_pods(namespace, kubeconfig, label="pods-main"))
    checks.append(_check_pods(minio_namespace, kubeconfig, label="pods-minio"))

    # 3) operator deployment
    checks.append(_check_operator_deployment(namespace, kubeconfig))

    # 4) CRD exists
    checks.append(_check_crd_exists(kubeconfig))

    # 5) IllustrationProject phases
    checks.append(_check_ilproj_phases(namespace, kubeconfig))

    # 6) Failed Jobs
    checks.append(_check_failed_jobs(namespace, kubeconfig))

    # 7) Projection UI /health
    checks.append(_check_projection_ui_health(ui_url))

    # 8) MinIO best-effort health
    checks.append(_check_minio_best_effort())

    return aggregate_status(checks)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Insurance Illustration Platform health check (thin slice)")
    parser.add_argument(
        "--kubeconfig",
        type=str,
        default=None,
        help="Path to kubeconfig file (defaults to KUBECONFIG env or kubectl defaults)",
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default="illustrations-poc",
        help="Kubernetes namespace for core platform workloads (default: illustrations-poc)",
    )
    parser.add_argument(
        "--minio-namespace",
        type=str,
        default="minio-system",
        help="Kubernetes namespace for MinIO workloads (default: minio-system)",
    )
    parser.add_argument(
        "--ui-url",
        type=str,
        default=None,
        help="Projection UI health URL (e.g. http://192.168.50.251:30301/health)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of human-readable text",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    summary = run_health_check(
        kubeconfig=args.kubeconfig,
        namespace=args.namespace,
        minio_namespace=args.minio_namespace,
        ui_url=args.ui_url,
    )

    if args.json:
        print(json.dumps(summary.to_dict(), indent=2))
    else:
        print(f"Overall status: {summary.status}")
        for c in summary.checks:
            status = "OK" if c.ok else "FAIL"
            crit = " (critical)" if c.critical else ""
            line = f"- {c.name}: {status}{crit}"
            if c.detail:
                line += f" – {c.detail}"
            print(line)

    return 0 if summary.status == "HEALTHY" else 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
