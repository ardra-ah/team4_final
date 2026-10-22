"""Phase 3 tests: LangGraph routing, human-in-the-loop, and error escalation.

Runs fully offline (no Gemini or Neon calls). Run from the project root:
    pytest tests/test_workflow.py -v
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "data" / "generator"))

from agents.workflow import build_graph, resume_claim, run_claim  # noqa: E402
from app.schemas import ClaimLabel, Decision, RoutePath  # noqa: E402
from generate_claims import build_claims  # noqa: E402

CLAIMS_DIR = ROOT / "data" / "claims"
POLICY_PDF = ROOT / "data" / "policies" / "policy_guidelines.pdf"
LABELS = [ClaimLabel(**row) for row in json.loads((CLAIMS_DIR / "labels.json").read_text())]
_, _, HISTORY = build_claims()  # same synthetic history that seed.sql loads into Postgres


@pytest.fixture(scope="module")
def app():
    return build_graph()


@pytest.fixture(scope="module")
def policy_store(tmp_path_factory):
    from agents.policy_rag import ingest

    persist = tmp_path_factory.mktemp("chroma_wf")
    ingest(str(POLICY_PDF), str(persist))
    return str(persist)


def _pdf(label: ClaimLabel) -> str:
    matches = list(CLAIMS_DIR.glob(f"{label.claim_id}_*.pdf"))
    assert len(matches) == 1
    return str(matches[0])


def _start(app, label, policy_store):
    return run_claim(app, label.claim_id, {
        "claim_id": label.claim_id,
        "pdf_path": _pdf(label),
        "claim_history": HISTORY,
        "policy_store": policy_store,
        "retry_backoff_s": 0.01,
    })


@pytest.mark.parametrize("label", LABELS, ids=[l.claim_id for l in LABELS])
def test_route_matches_label(app, policy_store, label):
    state = _start(app, label, policy_store)
    assert "__interrupt__" in state, "workflow should pause for human review"
    assert state["route"] == label.expected_path.value


@pytest.mark.parametrize("label", LABELS, ids=[l.claim_id for l in LABELS])
def test_final_decision_matches_label_after_review(app, policy_store, label):
    _start(app, label, policy_store)
    final = resume_claim(app, label.claim_id, None)  # accept the recommendation
    assert final["final_decision"] == label.expected_decision.value


def test_reviewer_can_override_recommendation(app, policy_store):
    label = next(l for l in LABELS if l.scenario == "clean")
    _start(app, label, policy_store)
    final = resume_claim(app, label.claim_id, Decision.REJECTED.value, note="Documents mismatch")
    assert final["final_decision"] == Decision.REJECTED.value
    assert final["reviewer_note"] == "Documents mismatch"


def test_invalid_reviewer_value_keeps_recommendation(app, policy_store):
    label = next(l for l in LABELS if l.scenario == "clean")
    _start(app, label, policy_store)
    final = resume_claim(app, label.claim_id, "MAYBE")
    assert final["final_decision"] == Decision.APPROVED.value


def test_policy_violation_carries_evidence(app, policy_store):
    label = next(l for l in LABELS if l.scenario == "policy_violation")
    state = _start(app, label, policy_store)
    assert state["policy_valid"] is False
    assert state["policy_reasons"]
    assert state["policy_evidence"], "RAG evidence should cite a policy section"


def test_duplicate_is_detected_against_history(app, policy_store):
    label = next(l for l in LABELS if l.scenario == "duplicate")
    state = _start(app, label, policy_store)
    assert "CLM-2026-HIST-001" in state["duplicate_of"]
    assert state["risk_level"] == "high"


def test_ocr_failure_escalates_after_retries(app, policy_store):
    state = run_claim(app, "CLM-MISSING-FILE", {
        "claim_id": "CLM-MISSING-FILE",
        "pdf_path": str(ROOT / "data" / "claims" / "does_not_exist.pdf"),
        "claim_history": HISTORY,
        "policy_store": policy_store,
        "retry_backoff_s": 0.01,
    })
    assert state["final_decision"] == Decision.ESCALATED.value
    assert "We could not read this PDF after 3 tries" in state["error"]
    assert "ocr: failed after 3 attempts" in state["audit"]
    assert "__interrupt__" not in state, "escalated claims skip human review"


def test_audit_trail_records_each_stage(app, policy_store):
    label = next(l for l in LABELS if l.scenario == "clean")
    _start(app, label, policy_store)
    final = resume_claim(app, label.claim_id, None)
    stages = " | ".join(final["audit"])
    for stage in ("ocr:", "extract:", "policy:", "fraud:", "router:", "recommendation:", "human:"):
        assert stage in stages


def test_gemini_text_is_used_when_enabled(app, policy_store, monkeypatch):
    import agents.llm as llm

    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("POLICY_EMBEDDINGS", "local")  # keep policy search offline in tests
    monkeypatch.setattr(llm, "call_gemini", lambda prompt: "GEMINI TEXT")
    label = next(l for l in LABELS if l.scenario == "clean")
    state = _start(app, label, policy_store)
    assert state["explanation"] == "GEMINI TEXT"
    assert any("explanation: gemini" in line for line in state["audit"])


def test_template_is_used_when_gemini_fails(app, policy_store, monkeypatch):
    import agents.llm as llm

    def broken(prompt):
        raise RuntimeError("network down")

    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("POLICY_EMBEDDINGS", "local")  # keep policy search offline in tests
    monkeypatch.setattr(llm, "call_gemini", broken)
    label = next(l for l in LABELS if l.scenario == "clean")
    state = _start(app, label, policy_store)
    assert state["explanation"]
    assert "All coverage checks passed" in state["explanation"]
    assert any("explanation: template" in line for line in state["audit"])
