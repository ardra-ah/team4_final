"""Deleting review runs from the API. Offline.

Run from the project root:  pytest tests/test_delete.py -v
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
def env(tmp_path):
    upload_dir = tmp_path / "uploads"
    service = ClaimService(
        upload_dir=upload_dir,
        policy_store=tmp_path / "chroma",
        history_loader=lambda: list(SEED_HISTORY),
        retry_backoff_s=0.01,
    )
    return TestClient(create_app(service=service)), upload_dir


def _upload(client, scenario="clean"):
    return client.post("/claims", files={"file": (f"{scenario}.pdf", _pdf_bytes(scenario), "application/pdf")}).json()


def test_delete_removes_run_and_its_pdf(env):
    client, upload_dir = env
    run = _upload(client, "clean")
    assert (upload_dir / f"{run['run_id']}.pdf").exists()

    r = client.delete(f"/claims/{run['run_id']}")
    assert r.status_code == 204
    assert client.get("/claims").json() == []
    assert client.get(f"/claims/{run['run_id']}").status_code == 404
    assert not (upload_dir / f"{run['run_id']}.pdf").exists()


def test_delete_unknown_claim_returns_404(env):
    client, _ = env
    assert client.delete("/claims/does-not-exist").status_code == 404


def test_deleting_original_clears_resubmission_link(env):
    client, _ = env
    original = client.post("/claims", files={"file": ("m.pdf", _pdf_bytes("missing_field"), "application/pdf")}).json()
    client.post(f"/claims/{original['run_id']}/decision", json={"decision": "PENDING_DOCUMENTS"})
    child = client.post(
        f"/claims/{original['run_id']}/resubmit",
        files={"file": ("c.pdf", _pdf_bytes("clean"), "application/pdf")},
    ).json()

    assert client.delete(f"/claims/{original['run_id']}").status_code == 204
    still_there = client.get(f"/claims/{child['run_id']}").json()
    assert still_there["parent_run_id"] is None


def test_deleting_resubmission_allows_resubmitting_again(env):
    client, _ = env
    original = client.post("/claims", files={"file": ("m.pdf", _pdf_bytes("missing_field"), "application/pdf")}).json()
    client.post(f"/claims/{original['run_id']}/decision", json={"decision": "PENDING_DOCUMENTS"})
    child = client.post(
        f"/claims/{original['run_id']}/resubmit",
        files={"file": ("c.pdf", _pdf_bytes("clean"), "application/pdf")},
    ).json()

    client.delete(f"/claims/{child['run_id']}")
    parent = client.get(f"/claims/{original['run_id']}").json()
    assert parent["resubmitted_as"] is None

    again = client.post(
        f"/claims/{original['run_id']}/resubmit",
        files={"file": ("again.pdf", _pdf_bytes("clean"), "application/pdf")},
    )
    assert again.status_code == 201
