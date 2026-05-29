from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

from fastapi.testclient import TestClient

from actuarypoc.ui.server import app


class _FakeObject:
  def __init__(self, object_name: str) -> None:
      self.object_name = object_name
      self.last_modified = datetime(2026, 1, 1)


class _FakeResponse:
  def __init__(self, data: bytes) -> None:
      self._data = data

  def read(self) -> bytes:  # pragma: no cover - trivial
      return self._data

  def close(self) -> None:  # pragma: no cover - trivial
      pass

  def release_conn(self) -> None:  # pragma: no cover - trivial
      pass


class _FakeMinioClient:
  def __init__(self, objects: Dict[str, bytes]) -> None:
      self._objects = objects

  def list_objects(self, bucket: str, prefix: str, recursive: bool = True):  # pragma: no cover - simple
      for name in self._objects.keys():
          if name.startswith(prefix):
              yield _FakeObject(name)

  def get_object(self, bucket: str, object_name: str) -> _FakeResponse:
      try:
          data = self._objects[object_name]
      except KeyError as exc:  # noqa: BLE001
          raise RuntimeError(f"Object not found: {object_name}") from exc
      return _FakeResponse(data)


def test_run_detail_api_premium_mismatch(monkeypatch, tmp_path):
  """Skeleton end-to-end test for the run-detail API.

  This uses a fake MinIO client and small synthetic inputs to exercise the
  /api/run-detail?key=... endpoint and verify that the RunDetail payload
  is structurally correct and surfaces premium reconciliation + audit
  evidence.
  """

  # 1) Create a tiny DSL file with premium_table + face_bands + docs.
  formula_path = tmp_path / "poc_term.yaml"
  formula_yaml = """
product_type: poc_term
meta:
  premium_table:
    source: minio
    prefix: "premium_tables/p12trf/"
    format: csv
    keys: [issue_age, gender, risk_class, face_band, level_period]
    value_column: premium_per_1000
    basis: annual_per_1000
    modalization:
      MONTHLY: divide_by_12
      ANNUAL: none
  face_bands:
    - band: 1
      min: 0
      max: 999999
  source_documents:
    actuarial_memo: "docs/p12trf/Actuarial_Memo.pdf"
    risk_mapping: "docs/p12trf/Risk_Mapping.pdf"
    premiums: "docs/p12trf/Premiums.pdf"
charges: []
credit_rates: []
"""
  formula_path.write_text(formula_yaml, encoding="utf-8")

  # 2) PAS snapshot on disk (referenced via file://).
  pas_payload = {
      "records": [
          {
              "policy_id": "P12TRF100001",
              "policy_number": "P12TRF100001",
              "product_code": "P12TRF",
              "product_type": "p12trf_term",
              "issue_age": 35,
              "gender": "M",
              "smoker_class": "NS",
              "risk_class": "SUPER_PREFERRED_NON_TOBACCO",
              "face_amount": 250000,
              "level_period": 10,
              "premium_mode": "MONTHLY",
              # Deliberately far from table-based expectation to force mismatch.
              "modal_premium": 180.0,
          }
      ]
  }
  pas_path = tmp_path / "pas.json"
  pas_path.write_text(json.dumps(pas_payload), encoding="utf-8")

  # 3) Premium table CSV in MinIO.
  premium_csv = """issue_age,gender,risk_class,face_band,level_period,premium_per_1000
35,M,SUPER_PREFERRED_NON_TOBACCO,1,10,0.80
"""

  # 4) Projection JSON in MinIO (minimal but structurally valid).
  projection_payload: Dict[str, Any] = {
      "generated_at": "2026-05-25T12:34:56Z",
      "inputs": {
          "pas_object": f"file://{pas_path}",
          "actuarial_object": "actuarial_tables/example.csv",
          "term23_actuarial_object": None,
          "rate_object": "rate_curves/example.csv",
          "crm_object": "crm_accounts/example.csv",
          "premium_table_object": "premium_tables/p12trf/prem.csv",
          "policy_id": "P12TRF100001",
          "product_id": "P12TRF",
          "product_code": "P12TRF",
          "formula_path": str(formula_path),
          "assumption_set_id": None,
      },
      "metadata": {
          "engine_version": "test-engine",
      },
      "warnings": [],
      "projection": {
          "years": [1, 2],
          "cash_values": [100.0, 200.0],
          "death_benefits": [250000.0, 250000.0],
          "mortality_rates": [0.0008, 0.00082],
          "survival_probabilities": [1.0, 0.9992],
          "net_level_premium": 50.0,
      },
  }

  objects = {
      "premium_tables/p12trf/prem.csv": premium_csv.encode("utf-8"),
      "projections/test_projection.json": json.dumps(projection_payload).encode("utf-8"),
  }

  fake_client = _FakeMinioClient(objects)

  # 5) Patch MinIO helpers to use the fake client + bucket.
  from actuarypoc import storage as _storage_pkg  # type: ignore[attr-defined]
  from actuarypoc.storage import minio_client as _minio_mod

  monkeypatch.setattr(_minio_mod, "get_minio_client", lambda: fake_client)
  monkeypatch.setattr(_minio_mod, "get_bucket_name", lambda: "test-bucket")

  # Also patch the aliases imported in ui.server.
  from actuarypoc.ui import server as _server_mod

  monkeypatch.setattr(_server_mod, "get_minio_client", lambda: fake_client)
  monkeypatch.setattr(_server_mod, "get_bucket_name", lambda: "test-bucket")

  client = TestClient(app)
  resp = client.get("/api/run-detail", params={"key": "projections/test_projection.json"})
  assert resp.status_code == 200

  data = resp.json()

  # Trust status should reflect the premium mismatch.
  assert data["trust_status"]["status"] == "warnings_found"

  # raw_record is null by default in customer-facing payload.
  assert data["policy_input"]["raw_record"] is None

  # Premium mismatch should be surfaced structurally.
  mismatch = data["premium_comparison"].get("mismatch")
  assert mismatch is not None
  assert mismatch["code"] == "premium_mismatch"

  # Audit sources should include the premium table object used.
  assert (
      data["audit_sources"]["objects"].get("premium_table_object")
      == "premium_tables/p12trf/prem.csv"
  )

  # Projection summary should have years populated.
  assert data["projection_summary"]["years"] == [1, 2]
