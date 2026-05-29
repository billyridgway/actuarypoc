from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict
import sys
import types

from fastapi.testclient import TestClient

sys.modules.setdefault("psycopg", types.SimpleNamespace())
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


def test_run_detail_api_missing_audit_record(monkeypatch, tmp_path):
  """RunDetail should succeed and return null audit_summary when no AuditRecord exists."""

  formula_path = tmp_path / "poc_term.yaml"
  formula_path.write_text("product_type: poc_term\nmeta: {}\ncharges: []\ncredit_rates: []\n", encoding="utf-8")

  pas_payload = {
      "records": [
          {
              "policy_id": "P12TRF100002",
              "policy_number": "P12TRF100002",
              "product_code": "P12TRF",
              "product_type": "p12trf_term",
              "issue_age": 40,
              "gender": "F",
              "smoker_class": "NS",
              "risk_class": "PREFERRED",
              "face_amount": 100000,
              "level_period": 10,
              "premium_mode": "ANNUAL",
              "modal_premium": 500.0,
          }
      ]
  }
  pas_path = tmp_path / "pas.json"
  pas_path.write_text(json.dumps(pas_payload), encoding="utf-8")

  projection_payload: Dict[str, Any] = {
      "generated_at": "2026-05-25T12:34:56Z",
      "inputs": {
          "pas_object": f"file://{pas_path}",
          "actuarial_object": "actuarial_tables/example.csv",
          "term23_actuarial_object": None,
          "rate_object": "rate_curves/example.csv",
          "crm_object": "crm_accounts/example.csv",
          "premium_table_object": None,
          "policy_id": "P12TRF100002",
          "product_id": "P12TRF",
          "product_code": "P12TRF",
          "run_id": "run-missing-audit",
          "formula_path": str(formula_path),
          "assumption_set_id": None,
      },
      "metadata": {
          "engine_version": "test-engine",
      },
      "warnings": [],
      "projection": {
          "years": [1],
          "cash_values": [50.0],
          "death_benefits": [100000.0],
          "mortality_rates": [0.0008],
          "survival_probabilities": [1.0],
          "net_level_premium": 10.0,
      },
  }

  objects = {
      "projections/test_missing_audit.json": json.dumps(projection_payload).encode("utf-8"),
  }

  fake_client = _FakeMinioClient(objects)

  from actuarypoc.storage import minio_client as _minio_mod
  from actuarypoc.ui import server as _server_mod

  monkeypatch.setattr(_minio_mod, "get_minio_client", lambda: fake_client)
  monkeypatch.setattr(_minio_mod, "get_bucket_name", lambda: "test-bucket")
  monkeypatch.setattr(_server_mod, "get_minio_client", lambda: fake_client)
  monkeypatch.setattr(_server_mod, "get_bucket_name", lambda: "test-bucket")

  client = TestClient(app)
  resp = client.get("/api/run-detail", params={"key": "projections/test_missing_audit.json"})
  assert resp.status_code == 200

  data = resp.json()

  # When no AuditRecord exists, audit_summary should be null and the API should still succeed.
  assert data.get("audit_summary") is None
