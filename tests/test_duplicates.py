"""Re-uploading the same file: blocked while open, flagged when already decided. Offline.

Run from the project root:  pytest tests/test_duplicates.py -v
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
    return next(CLAIMS_DIR.glob(f"{claim_id}_*.pdf")).read_bytes()


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
    return client.post("/claims", files={"file": (f"{scenario}.pdf", _pdf_bytes(scenario), "application/pdf")})


def test_identical_file_is_refused_while_first_is_in_review(client):
    first = _upload(client, "clean").json()
    assert first["status"] == "awaiting_review"

    again = _upload(client, "clean")
    assert again.status_code == 409
    assert first["run_id"] in again.json()["detail"]
    assert "already in review" in again.json()["detail"]
    assert len(client.get("/claims").json()) == 1


def test_identical_file_is_flagged_as_duplicate_after_a_decision(client):
    first = _upload(client, "clean").json()
    client.post(f"/claims/{first['run_id']}/decision", json={"decision": "APPROVED"})

    second = _upload(client, "clean")
    assert second.status_code == 201
    body = second.json()
    assert first["claim_id"] in body["duplicate_of"]
    assert body["route"] == "investigation"
    assert body["status"] == "awaiting_review"


def test_identical_file_is_refused_while_documents_are_requested(client):
    original = _upload(client, "missing_field").json()
    client.post(f"/claims/{original['run_id']}/decision", json={"decision": "PENDING_DOCUMENTS"})

    again = _upload(client, "missing_field")
    assert again.status_code == 409


def test_different_file_is_not_blocked(client):
    _upload(client, "clean")
    other = _upload(client, "missing_field")
    assert other.status_code == 201


def test_deleting_the_open_claim_allows_uploading_again(client):
    first = _upload(client, "clean").json()
    assert client.delete(f"/claims/{first['run_id']}").status_code == 204
    assert _upload(client, "clean").status_code == 201
