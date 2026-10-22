"""Edge cases for uploads, extraction, rules, API calls, and failing dependencies. Offline.

Run from the project root:  pytest tests/test_edge_cases.py -v
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "data" / "generator"))

from app import service as service_module  # noqa: E402
from app.main import create_app  # noqa: E402
from app.service import SEED_HISTORY, ClaimService, RunStore, load_history  # noqa: E402
from make_demo_claims import COMPLETE, write_text_pdf  # noqa: E402

# A procedure with no typical rate, so the abnormal-amount rule does not interfere.
NO_RATE_PROCEDURE = "99281"


def make_pdf(tmp_path: Path, changes: dict | None = None, name: str = "claim") -> bytes:
    """Build a text-layer claim PDF. changes maps form labels to values; None drops the line."""
    fields = dict(COMPLETE)
    fields.update(changes or {})
    path = tmp_path / f"{name}.pdf"
    write_text_pdf(path, fields)
    return path.read_bytes()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    # Keep these tests offline and independent of the developer's .env.
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


def post(client, data: bytes, filename: str = "claim.pdf"):
    return client.post("/claims", files={"file": (filename, data, "application/pdf")})


def decide(client, run_id: str, decision: str, note: str = ""):
    return client.post(f"/claims/{run_id}/decision", json={"decision": decision, "note": note})


# 1-5: uploaded files that are not clean claim PDFs -------------------------------

def test_01_renamed_text_file_is_escalated_without_crashing(env):
    client, _ = env
    r = post(client, b"this is a plain text file, not a PDF")
    assert r.status_code == 201
    assert r.json()["final_decision"] == "ESCALATED"
    assert r.json()["error"]


def test_02_truncated_pdf_is_escalated_without_crashing(env):
    client, tmp = env
    data = make_pdf(tmp)[:300]
    r = post(client, data)
    assert r.status_code == 201
    assert r.json()["final_decision"] == "ESCALATED"


def test_03_password_protected_pdf_is_not_approved(env):
    client, tmp = env
    plain = tmp / "plain.pdf"
    plain.write_bytes(make_pdf(tmp))
    locked = tmp / "locked.pdf"
    doc = fitz.open(plain)
    doc.save(locked, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret")
    r = post(client, locked.read_bytes())
    assert r.status_code == 201
    assert r.json()["recommended_decision"] != "APPROVED"


def test_04_blank_pdf_is_not_approved(env):
    client, tmp = env
    doc = fitz.open()
    doc.new_page()
    blank = tmp / "blank.pdf"
    doc.save(blank)
    r = post(client, blank.read_bytes())
    assert r.status_code == 201
    assert r.json()["recommended_decision"] != "APPROVED"


def test_05_uppercase_extension_and_odd_filename_are_accepted(env):
    client, tmp = env
    r = post(client, make_pdf(tmp), filename='<img src=x onerror="alert(1)">.PDF')
    assert r.status_code == 201
    assert r.json()["filename"].endswith(".PDF")


# 6-12: extracted values and rules -----------------------------------------------

def test_06_billed_less_than_claimed_is_not_approved(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {
        "Procedure Code": NO_RATE_PROCEDURE,
        "Billed Amount": "100.00 USD",
        "Claimed Amount": "180.00 USD",
    }))
    assert r.status_code == 201
    assert r.json()["recommended_decision"] != "APPROVED"


def test_07a_claim_exactly_at_limit_is_approved(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {
        "Procedure Code": NO_RATE_PROCEDURE,
        "Billed Amount": "5000.00 USD",
        "Claimed Amount": "5000.00 USD",
    }))
    assert r.json()["recommended_decision"] == "APPROVED"


def test_07b_claim_one_cent_over_limit_is_rejected(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {
        "Procedure Code": NO_RATE_PROCEDURE,
        "Billed Amount": "5000.01 USD",
        "Claimed Amount": "5000.01 USD",
    }))
    assert r.json()["recommended_decision"] == "REJECTED"


def test_08a_service_on_last_waiting_day_is_inside_the_waiting_period(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {
        "Procedure Code": NO_RATE_PROCEDURE,
        "Service Date": "2026-08-30",
    }))
    assert r.json()["recommended_decision"] == "REJECTED"


def test_08b_service_on_first_day_after_waiting_period_is_approved(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {
        "Procedure Code": NO_RATE_PROCEDURE,
        "Service Date": "2026-08-31",
    }))
    assert r.json()["recommended_decision"] == "APPROVED"


@pytest.mark.parametrize("bad_date", ["31/02/2026", "next Tuesday"])
def test_09a_unreadable_service_date_is_flagged_as_missing(env, bad_date):
    client, tmp = env
    r = post(client, make_pdf(tmp, {"Service Date": bad_date}))
    assert r.status_code == 201
    assert "service_date" in r.json()["missing_fields"]
    assert r.json()["recommended_decision"] != "APPROVED"


def test_09b_impossible_calendar_date_is_flagged_not_crashed(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {"Service Date": "2026-02-31"}))
    assert r.status_code == 201
    assert r.json()["recommended_decision"] != "APPROVED"


@pytest.mark.parametrize("amount", ["-50.00 USD", "0.00 USD"])
def test_10_negative_or_zero_amount_is_not_approved(env, amount):
    client, tmp = env
    r = post(client, make_pdf(tmp, {
        "Procedure Code": NO_RATE_PROCEDURE,
        "Billed Amount": amount,
        "Claimed Amount": amount,
    }))
    assert r.status_code == 201
    assert r.json()["recommended_decision"] != "APPROVED"


def test_10b_non_numeric_amount_is_flagged_as_missing(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {"Billed Amount": "abc", "Claimed Amount": "abc"}))
    assert {"billed_amount", "claimed_amount"} <= set(r.json()["missing_fields"])


def test_11_non_usd_claim_is_not_auto_approved(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {
        "Procedure Code": NO_RATE_PROCEDURE,
        "Billed Amount": "3000.00 EUR",
        "Claimed Amount": "3000.00 EUR",
    }))
    assert r.json()["recommended_decision"] != "APPROVED"


def test_12_missing_claim_id_is_flagged_and_run_completes(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {"Claim ID": None}))
    assert r.status_code == 201
    assert "claim_id" in r.json()["missing_fields"]
    assert r.json()["recommended_decision"] == "PENDING_DOCUMENTS"


# 13-15: duplicate and routing priority -----------------------------------------

def test_13_same_member_provider_date_and_procedure_is_a_duplicate(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {
        "Claim ID": "CLM-OTHER-0001",
        "Member ID": "MBR-99901",
        "Provider ID": "PRV-0042",
        "Service Date": "2026-08-14",
        "Procedure Code": "99213",
    }))
    assert r.json()["duplicate_of"] == ["CLM-2026-HIST-001"]
    assert r.json()["route"] == "investigation"


def test_14_missing_fields_take_priority_over_duplicate(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {
        "Claim ID": "CLM-OTHER-0002",
        "Member ID": "MBR-99901",
        "Provider ID": "PRV-0042",
        "Service Date": "2026-08-14",
        "Procedure Code": "99213",
        "Diagnosis Code": None,
    }))
    assert r.json()["route"] == "clarification"
    assert r.json()["recommended_decision"] == "PENDING_DOCUMENTS"


def test_15_cosmetic_procedure_goes_to_rejection_review(env):
    client, tmp = env
    r = post(client, make_pdf(tmp, {"Procedure Code": "15820"}))
    assert r.json()["route"] == "rejection_review"
    assert r.json()["recommended_decision"] == "REJECTED"


# 16-19: API misuse ----------------------------------------------------------------

def test_16a_invalid_decision_value_is_rejected(env):
    client, tmp = env
    run = post(client, make_pdf(tmp)).json()
    assert decide(client, run["run_id"], "MAYBE").status_code == 422


def test_16b_decision_on_unknown_claim_returns_404(env):
    client, _ = env
    assert decide(client, "does-not-exist", "APPROVED").status_code == 404


def test_16c_very_long_note_is_accepted(env):
    client, tmp = env
    run = post(client, make_pdf(tmp)).json()
    assert decide(client, run["run_id"], "APPROVED", "x" * 100_000).status_code == 200


def test_17_deciding_twice_returns_409(env):
    client, tmp = env
    run = post(client, make_pdf(tmp)).json()
    assert decide(client, run["run_id"], "APPROVED").status_code == 200
    assert decide(client, run["run_id"], "REJECTED").status_code == 409


def test_18a_resubmitting_twice_returns_409(env):
    client, tmp = env
    original = post(client, make_pdf(tmp, {"Diagnosis Code": None}, name="missing")).json()
    decide(client, original["run_id"], "PENDING_DOCUMENTS")
    first = client.post(f"/claims/{original['run_id']}/resubmit",
                        files={"file": ("fixed.pdf", make_pdf(tmp), "application/pdf")})
    assert first.status_code == 201
    second = client.post(f"/claims/{original['run_id']}/resubmit",
                         files={"file": ("fixed2.pdf", make_pdf(tmp, {"Claim ID": "CLM-X-9"}), "application/pdf")})
    assert second.status_code == 409


def test_18b_resubmitting_a_claim_not_waiting_for_documents_returns_409(env):
    client, tmp = env
    run = post(client, make_pdf(tmp)).json()
    r = client.post(f"/claims/{run['run_id']}/resubmit",
                    files={"file": ("x.pdf", make_pdf(tmp, {"Claim ID": "CLM-X-8"}), "application/pdf")})
    assert r.status_code == 409


def test_18c_resubmitting_the_identical_file_returns_409(env):
    client, tmp = env
    data = make_pdf(tmp, {"Diagnosis Code": None}, name="missing")
    original = post(client, data).json()
    decide(client, original["run_id"], "PENDING_DOCUMENTS")
    r = client.post(f"/claims/{original['run_id']}/resubmit", files={"file": ("same.pdf", data, "application/pdf")})
    assert r.status_code == 409


def test_19_deleting_twice_returns_404_the_second_time(env):
    client, tmp = env
    run = post(client, make_pdf(tmp)).json()
    assert client.delete(f"/claims/{run['run_id']}").status_code == 204
    assert client.delete(f"/claims/{run['run_id']}").status_code == 404


# 20: concurrency -------------------------------------------------------------------

def test_20_simultaneous_uploads_are_all_saved(env):
    client, tmp = env
    files = [make_pdf(tmp, {"Claim ID": f"CLM-CONC-{i:02d}"}, name=f"c{i}") for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda data: post(client, data), files))
    assert all(r.status_code == 201 for r in responses)
    assert len(client.get("/claims").json()) == 8


# 21-23: dependencies that fail ----------------------------------------------------

def test_21a_unreachable_database_still_saves_runs_in_memory(env):
    client, tmp = env
    store = RunStore("postgresql://user:pass@127.0.0.1:1/none")
    assert store.enabled is False
    svc = ClaimService(upload_dir=tmp / "u2", policy_store=tmp / "c2",
                       history_loader=lambda: list(SEED_HISTORY), retry_backoff_s=0.01, run_store=store)
    r = TestClient(create_app(service=svc)).post("/claims", files={"file": ("a.pdf", make_pdf(tmp), "application/pdf")})
    assert r.status_code == 201


def test_21b_unreachable_database_falls_back_to_seed_history(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@127.0.0.1:1/none")
    assert load_history() == list(SEED_HISTORY)


def test_22_gemini_failure_uses_template_and_says_why(env, monkeypatch):
    client, tmp = env
    import agents.llm as llm

    def broken(prompt):
        raise RuntimeError("quota exceeded")

    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(llm, "call_gemini", broken)
    r = post(client, make_pdf(tmp))
    assert r.status_code == 201
    assert r.json()["recommended_decision"] == "APPROVED"
    audit = " ".join(r.json()["audit"])
    assert "explanation: template (Gemini was unavailable)" in audit


def test_23_missing_policy_store_does_not_crash_the_run(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POLICY_EMBEDDINGS", "local")
    monkeypatch.setenv("LLM_ENABLED", "0")
    monkeypatch.setattr(service_module, "ingest", lambda *args, **kwargs: None)
    svc = ClaimService(upload_dir=tmp_path / "u", policy_store=tmp_path / "empty-chroma",
                       history_loader=lambda: list(SEED_HISTORY), retry_backoff_s=0.01)
    client = TestClient(create_app(service=svc))
    r = post(client, make_pdf(tmp_path, {"Procedure Code": NO_RATE_PROCEDURE, "Service Date": "2026-08-14"}))
    assert r.status_code == 201
    assert r.json()["recommended_decision"] == "REJECTED"
