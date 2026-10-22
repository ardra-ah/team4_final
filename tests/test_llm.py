"""Phase 6b tests for the Gemini explanation step. Offline: no real Gemini calls.

Run from the project root:  pytest tests/test_llm.py -v
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import agents.llm as llm  # noqa: E402

FACTS = {"Claim ID": "CLM-2026-0001", "Route": "approval", "Decision": "APPROVED"}


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LLM_ENABLED", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm.explain(FACTS, call=lambda p: "should not run") is None


def test_needs_api_key_too(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm.explain(FACTS, call=lambda p: "should not run") is None


def test_returns_model_text(enabled):
    assert llm.explain(FACTS, call=lambda p: "Approved because all checks passed.") == \
        "Approved because all checks passed."


def test_retries_then_gives_up(enabled):
    calls = []

    def failing(prompt):
        calls.append(prompt)
        raise RuntimeError("timeout")

    assert llm.explain(FACTS, call=failing, attempts=2) is None
    assert len(calls) == 2


def test_prompt_contains_facts_and_rules():
    prompt = llm.build_prompt(FACTS)
    assert "Do not change or question the decision" in prompt
    assert "- Decision: APPROVED" in prompt
    assert "- Claim ID: CLM-2026-0001" in prompt
