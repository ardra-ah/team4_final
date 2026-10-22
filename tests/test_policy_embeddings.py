"""Policy search embeddings: offline by default, Gemini when enabled, fallback on failure.

Run from the project root:  pytest tests/test_policy_embeddings.py -v
Gemini itself is never called: the Gemini embedding class is replaced with a fake.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents import policy_rag  # noqa: E402

POLICY_PDF = ROOT / "data" / "policies" / "policy_guidelines.pdf"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("LLM_ENABLED", "GEMINI_API_KEY", "POLICY_EMBEDDINGS"):
        monkeypatch.delenv(var, raising=False)


def test_offline_by_default(tmp_path):
    assert policy_rag.gemini_active() is False
    assert policy_rag.ingest(str(POLICY_PDF), str(tmp_path)) > 0
    hits = policy_rag.query("coverage limit", str(tmp_path), k=1)
    assert hits and "title" in hits[0]


def test_local_override_wins_even_when_gemini_is_configured(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("POLICY_EMBEDDINGS", "local")
    assert policy_rag.gemini_active() is False


def test_gemini_vectors_are_used_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    calls = []

    def fake_embed(self, input):
        calls.append(len(input))
        return [[1.0] * policy_rag.GEMINI_EMBED_DIM for _ in input]

    monkeypatch.setattr(policy_rag.GeminiEmbedding, "__call__", fake_embed)
    chunks = policy_rag.ingest(str(POLICY_PDF), str(tmp_path))
    assert chunks > 0 and calls, "Gemini embedding should have been called during ingest"
    hits = policy_rag.query("coverage limit", str(tmp_path), k=1)
    assert hits


def test_gemini_failure_falls_back_to_offline_index(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def broken(self, input):
        raise RuntimeError("network down")

    monkeypatch.setattr(policy_rag.GeminiEmbedding, "__call__", broken)
    assert policy_rag.ingest(str(POLICY_PDF), str(tmp_path)) > 0  # does not raise
    hits = policy_rag.query("coverage limit", str(tmp_path), k=1)
    assert hits, "query should fall back to the offline index"
