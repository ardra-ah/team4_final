"""Member identifiers must not leave the API, but duplicate checks must still work. Offline.

Run from the project root:  pytest tests/test_privacy.py -v
"""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "data" / "generator"))

from app.main import create_app  # noqa: E402
from app.service import SEED_HISTORY, ClaimService  # noqa: E402
from make_demo_claims import write_text_pdf  # noqa: E402
from generate_claims import build_claims  # noqa: E402

CLAIMS_DIR = ROOT / "data" / "claims"
LABELS = json.loads((CLAIMS_DIR / "labels.json").read_text())
HIDDEN = ("member_id", "member_name")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POLICY_EMBEDDINGS", "local")
    monkeypatch.setenv("LLM_ENABLED", "0")
    service = ClaimService(
        upload_dir=tmp_path / "uploads",
        policy_store=tmp_path / "chroma",
        history_loader=lambda: list(SEED_HISTORY),
        retry_backoff_s=0.01,
    )
    return TestClient(create_app(service=service)), tmp_path


def _pdf_bytes(scenario: str) -> bytes:
    claim_id = next(r["claim_id"] for r in LABELS if r["scenario"] == scenario)
    return next(CLAIMS_DIR.glob(f"{claim_id}_*.pdf")).read_bytes()


def _assert_hidden(body: dict):
    extraction = body.get("extraction") or {}
    for field in HIDDEN:
        assert field not in extraction, f"{field} leaked in API response"
    assert "MBR-" not in json.dumps(body), "member ID value leaked in API response"


def test_upload_response_hides_member_fields(client):
    api, _ = client
    r = api.post("/claims", files={"file": ("c.pdf", _pdf_bytes("clean"), "application/pdf")})
    assert r.status_code == 201
    _assert_hidden(r.json())


def test_get_and_list_hide_member_fields(client):
    api, _ = client
    run = api.post("/claims", files={"file": ("c.pdf", _pdf_bytes("clean"), "application/pdf")}).json()
    _assert_hidden(api.get(f"/claims/{run['run_id']}").json())
    for item in api.get("/claims").json():
        _assert_hidden(item)


def test_decision_response_hides_member_fields(client):
    api, _ = client
    run = api.post("/claims", files={"file": ("c.pdf", _pdf_bytes("clean"), "application/pdf")}).json()
    r = api.post(f"/claims/{run['run_id']}/decision", json={"decision": "APPROVED"})
    assert r.status_code == 200
    _assert_hidden(r.json())


def test_duplicate_detection_still_works_without_exposing_member(client):
    api, tmp = client
    # The seed history claim belongs to MBR-99901; the duplicate rule must still match it.
    dup_pdf = tmp / "dup.pdf"
    write_text_pdf(dup_pdf, {
        "Claim ID": "CLM-PRIVACY-DUP",
        "Member ID": "MBR-99901",
        "Provider ID": "PRV-0042",
        "Service Date": "2026-08-14",
        "Procedure Code": "99213",
    })
    r = api.post("/claims", files={"file": ("dup.pdf", dup_pdf.read_bytes(), "application/pdf")})
    assert r.status_code == 201
    body = r.json()
    assert body["duplicate_of"] == ["CLM-2026-HIST-001"]
    _assert_hidden(body)
