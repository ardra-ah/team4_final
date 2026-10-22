"""Phase 5 tests: FastAPI endpoints for upload, review, and decisions. Offline.

Run from the project root:  pytest tests/test_api.py -v
"""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.main import create_app  # noqa: E402
from app.service import SEED_HISTORY, ClaimService  # noqa: E402

CLAIMS_DIR = ROOT / "data" / "claims"
LABELS = {row["scenario"]: row for row in json.loads((CLAIMS_DIR / "labels.json").read_text())}


def _pdf_bytes(scenario: str) -> bytes:
    claim_id = LABELS[scenario]["claim_id"]
    path = next(CLAIMS_DIR.glob(f"{claim_id}_*.pdf"))
    return path.read_bytes()


@pytest.fixture()
def client(tmp_path):
    service = ClaimService(
        upload_dir=tmp_path / "uploads",
        policy_store=tmp_path / "chroma",
        history_loader=lambda: list(SEED_HISTORY),
        retry_backoff_s=0.01,
    )
    return TestClient(create_app(service=service))


def _upload(client, scenario="clean"):
    return client.post(
        "/claims",
        files={"file": (f"{scenario}.pdf", _pdf_bytes(scenario), "application/pdf")},
    )


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_clean_claim_waits_for_review_then_approves(client):
    r = _upload(client, "clean")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "awaiting_review"
    assert body["route"] == "approval"
    assert body["recommended_decision"] == "APPROVED"

    done = client.post(f"/claims/{body['run_id']}/decision", json={"decision": "APPROVED", "note": "ok"})
    assert done.status_code == 200
    assert done.json()["status"] == "completed"
    assert done.json()["final_decision"] == "APPROVED"
    assert done.json()["reviewer_note"] == "ok"


def test_reviewer_can_override(client):
    run_id = _upload(client, "clean").json()["run_id"]
    body = client.post(f"/claims/{run_id}/decision", json={"decision": "REJECTED"}).json()
    assert body["final_decision"] == "REJECTED"


def test_duplicate_claim_routes_to_investigation(client):
    body = _upload(client, "duplicate").json()
    assert body["route"] == "investigation"
    assert body["duplicate_of"] == ["CLM-2026-HIST-001"]


def test_missing_field_is_reported(client):
    body = _upload(client, "missing_field").json()
    assert body["route"] == "clarification"
    assert "diagnosis_code" in body["missing_fields"]


def test_invalid_decision_is_rejected(client):
    run_id = _upload(client, "clean").json()["run_id"]
    r = client.post(f"/claims/{run_id}/decision", json={"decision": "MAYBE"})
    assert r.status_code == 422


def test_deciding_twice_returns_conflict(client):
    run_id = _upload(client, "clean").json()["run_id"]
    client.post(f"/claims/{run_id}/decision", json={"decision": "APPROVED"})
    r = client.post(f"/claims/{run_id}/decision", json={"decision": "REJECTED"})
    assert r.status_code == 409


def test_unknown_claim_returns_404(client):
    assert client.get("/claims/does-not-exist").status_code == 404
    assert client.post("/claims/does-not-exist/decision", json={"decision": "APPROVED"}).status_code == 404


def test_non_pdf_upload_is_rejected(client):
    r = client.post("/claims", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 422


def test_empty_pdf_is_rejected(client):
    r = client.post("/claims", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert r.status_code == 422


def test_list_returns_all_runs(client):
    _upload(client, "clean")
    _upload(client, "policy_violation")
    runs = client.get("/claims").json()
    assert len(runs) == 2
