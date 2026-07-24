# Product Workspace v1 Step 2 Review Evidence

> **Status:** Builder implementation evidence; independent Auditor review pending
> **Date:** 2026-07-23
> **Task contract:** `PRODUCT_WORKSPACE_V1_STEP2_TASK_CONTRACT.md`

## 1. Repository identity

- Assigned branch: `agent/actuary-pilot-20260722-222609`
- Clean baseline and parent required by contract:
  `55d27367d8d8ca9a4343368c79d0bbed5a2173a2`
- Baseline subject: `Record Product Workspace Step 1 approval`
- Implementation commit: recorded in the Builder handoff after this evidence is
  committed.

## 2. Implemented behavior

- Every existing UL requirement emits canonical `requirementId`, `impact` and
  `materiality`, `applicability`, `implementationState`, `inputState`, and
  `isBlockingGap` fields.
- The existing deterministic classifier remains the blocking-rule authority;
  confirmed-not-applicable requirements now deterministically use
  `inputState=not_required`.
- Applicability is resolved before missingness. `needs_review` and
  `confirmed_not_applicable` items cannot enter `missingInformation` or the
  blocking list.
- Missing-input, unsupported-capability, and unresolved-capability lists are
  independently derived and may intentionally contain the same canonical
  requirement when multiple gaps are true.
- The narrow existing-UL engine map declares only:
  - level policy/admin fee behavior as supported;
  - the flat COI placeholder as unsupported for a filed COI table;
  - the runtime surrender approximation as unsupported for a filed schedule.
  Absent declarations remain unresolved and never default supported.
- Canonical provenance uses `product_document`, `deterministic_rule`, and
  `engine_configuration`. Explicit placeholder/default/fallback values use
  those unsafe provenance kinds and are not marked document- or AI-extracted.
- `readinessContractVersion` is `1.0`. Existing top-level analysis, workspace
  and document identity, product identity/provenance, `readiness`,
  `readinessDashboard`, `requirements`, and legacy requirement keys remain.
  Presentation applicability is retained as `legacyApplicability`.

## 3. Acceptance mapping

| Acceptance area | Evidence |
|---|---|
| Supported UL canonical shape and engine provenance | `test_canonical_classification_shape_and_legacy_aliases`; `test_explicit_scoped_engine_capability_has_non_document_provenance` |
| Second UL identity without Promise/P12TRF contamination | `test_second_ul_identity_does_not_share_promise_or_term_fallback` |
| Honest unavailable product types | `test_unsupported_or_unresolved_product_type_is_analysis_unavailable`; endpoint unavailable regression |
| Missing input independent of capability | `test_missing_input_and_capability_gaps_are_independent` |
| Explicit unsupported independent of missing input | same dual-gap test covers COI in both lists |
| Unresolved applicability nonmissing/nonblocking | `test_applicability_precedes_missingness_and_document_requests` |
| Not applicable is not required/nonblocking/not requested | same applicability-ordering test |
| Unknown capability never defaults supported | dual-gap test and existing missing-declaration test |
| Placeholder/default/fallback is unsafe | `test_placeholder_default_or_fallback_input_is_not_ready_or_document_extracted` |
| Legacy response compatibility | canonical-shape test and existing analyzer tests |
| Step 1 exact-document/input validation | analyzer exact-input test and all boundary tests |
| Endpoint serialized/persisted shape | `test_endpoint_persists_canonical_readiness_shape` |

## 4. Exact validation commands and results

1. Baseline inspection:

   `git status --short && git branch --show-current && git rev-parse HEAD && git log -1 --oneline`

   Result: clean tree; assigned branch; exact required baseline
   `55d27367d8d8ca9a4343368c79d0bbed5a2173a2`.

2. Prescribed unqualified interpreter attempt:

   `python -m pytest -q src/actuarypoc/tests/test_workspace_ul_analyzer.py src/actuarypoc/tests/test_requirements_classification.py`

   Result: did not start; `python` is not installed on `PATH`.

3. System Python attempt:

   `python3 -m pytest -q src/actuarypoc/tests/test_workspace_ul_analyzer.py src/actuarypoc/tests/test_requirements_classification.py`

   Result: did not start; system Python has no `pytest` module.

4. Repository shared virtual environment, combined analyzer/classifier attempt:

   `PYTHONPATH=src /Users/advisor/.openclaw/workspace/actuarypoc/.venv/bin/python -m pytest -q src/actuarypoc/tests/test_workspace_ul_analyzer.py src/actuarypoc/tests/test_requirements_classification.py`

   Result: collection stopped on the pre-existing Python 3.9
   `str | None` annotation in `test_requirements_classification.py`; 2 dependency
   warnings. This is the contract's known nonblocking limitation.

5. Focused analyzer suite after implementation:

   `PYTHONPATH=src /Users/advisor/.openclaw/workspace/actuarypoc/.venv/bin/python -m pytest -q src/actuarypoc/tests/test_workspace_ul_analyzer.py`

   Result: **10 passed**, 2 dependency warnings.

6. Step 1 boundary and endpoint regression suite:

   `PYTHONPATH=src /Users/advisor/.openclaw/workspace/actuarypoc/.venv/bin/python -m pytest -q src/actuarypoc/tests/test_workspace_analysis_boundary.py`

   Result: **5 passed**, 3 dependency warnings.

7. Existing capability/feature-request regression suite:

   `PYTHONPATH=src /Users/advisor/.openclaw/workspace/actuarypoc/.venv/bin/python -m pytest -q src/actuarypoc/tests/test_capabilities_and_feature_requests.py`

   Result: **4 passed**.

8. Final combined focused and regression suite:

   `PYTHONPATH=src /Users/advisor/.openclaw/workspace/actuarypoc/.venv/bin/python -m pytest -q src/actuarypoc/tests/test_workspace_ul_analyzer.py src/actuarypoc/tests/test_workspace_analysis_boundary.py src/actuarypoc/tests/test_capabilities_and_feature_requests.py`

   Result: **19 passed**, 3 dependency warnings.

9. Compile check:

   `PYTHONPYCACHEPREFIX=/tmp/actuarypoc-step2-pycache /Users/advisor/.openclaw/workspace/actuarypoc/.venv/bin/python -m compileall -q src/actuarypoc/domain/requirements_classification.py src/actuarypoc/extract/workspace_ul_analyzer.py src/actuarypoc/tests/test_workspace_ul_analyzer.py src/actuarypoc/tests/test_workspace_analysis_boundary.py`

   Result: exit 0, no output.

10. Diff check:

    `git diff --check`

    Result: exit 0, no output.

11. Product-specific reference scan:

    `rg -n "Promise|PROMISE|P12TRF|ICC18 P18PR|HARBOR-FUL-7|CAN-UL|GAP-UL|APP-UL|UNSAFE-UL" src/actuarypoc/domain/requirements_classification.py src/actuarypoc/extract/workspace_ul_analyzer.py src/actuarypoc/tests/test_workspace_ul_analyzer.py src/actuarypoc/tests/test_workspace_analysis_boundary.py`

    Result: no product code, carrier, form, or fixture identity occurs in the
    changed analyzer. Existing Promise wording remains only in generic
    classifier documentation and representative/cross-contamination tests;
    fixture identities remain confined to tests.

## 5. Warnings and limitations

- The shared virtual environment is Python 3.9. The pre-existing use of
  `str | None` in `test_requirements_classification.py` prevents that module
  from collecting. Step 2 does not introduce or broaden that syntax. The
  modified classifier path is exercised by all analyzer tests and passes
  compileall, but the generic classifier module's existing tests were not
  executable in this environment.
- Dependency warnings are unchanged: PyPDF2 deprecation, urllib3 LibreSSL
  compatibility, and Starlette multipart pending deprecation.
- This is a deterministic bounded key/value analyzer, not richer extraction, a
  general capability registry, a new engine, or projection enforcement.
- No live validation, merge, push, deployment, Kubernetes change, or MinIO
  projection-object validation was performed; all are outside scope or
  explicitly prohibited.
- Independent Auditor review is pending. The implementation is not approved for
  merge or deployment.
