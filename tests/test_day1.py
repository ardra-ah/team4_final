"""Day 1 tests: synthetic data, OCR, extraction, and policy chunking.

Run from the project root:  pytest tests/ -v
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from agents.ocr import extract_text  # noqa: E402
from agents.extraction import extract_claim  # noqa: E402
from agents.policy_rag import chunk_policy_text, read_policy_pdf  # noqa: E402
from app.schemas import ClaimLabel, Decision, RoutePath  # noqa: E402

CLAIMS_DIR = ROOT / "data" / "claims"
POLICY_PDF = ROOT / "data" / "policies" / "policy_guidelines.pdf"
LABELS = [ClaimLabel(**row) for row in json.loads((CLAIMS_DIR / "labels.json").read_text())]


def _pdf_for(label: ClaimLabel) -> Path:
    matches = list(CLAIMS_DIR.glob(f"{label.claim_id}_*.pdf"))
    assert len(matches) == 1, f"expected one PDF for {label.claim_id}"
    return matches[0]


def test_labels_cover_twenty_claims():
    assert len(LABELS) == 20
    assert {l.scenario for l in LABELS} == {
        "clean", "missing_field", "policy_violation", "duplicate", "high_fraud"
    }


def test_labels_use_only_contract_enums():
    for label in LABELS:
        assert isinstance(label.expected_path, RoutePath)
        assert isinstance(label.expected_decision, Decision)


def test_scanned_claim_uses_ocr_fallback():
    label = LABELS[0]  # generator writes the first claim as a scanned image PDF
    raw, source = extract_text(str(_pdf_for(label)))
    assert source == "scanned_pdf"
    assert "Claim ID" in raw


def test_text_claim_uses_text_layer():
    label = LABELS[1]
    raw, source = extract_text(str(_pdf_for(label)))
    assert source == "text_pdf"
    assert "Claim ID" in raw


@pytest.mark.parametrize("label", LABELS, ids=[l.claim_id for l in LABELS])
def test_extraction_matches_ground_truth(label):
    raw, source = extract_text(str(_pdf_for(label)))
    claim = extract_claim(raw, source)
    assert claim.claim_id == label.claim_id
    assert claim.missing_fields == label.expected_missing_fields


def test_extraction_parses_amounts_and_dates():
    raw, source = extract_text(str(_pdf_for(LABELS[1])))
    claim = extract_claim(raw, source)
    assert isinstance(claim.billed_amount, float) and claim.billed_amount > 0
    assert claim.service_date is not None
    assert claim.procedure_code and claim.procedure_code.isdigit()


def test_missing_diagnosis_is_detected():
    label = next(l for l in LABELS if l.scenario == "missing_field")
    raw, source = extract_text(str(_pdf_for(label)))
    claim = extract_claim(raw, source)
    assert "diagnosis_code" in claim.missing_fields
    assert claim.diagnosis_code is None


def test_policy_pdf_chunks_into_numbered_sections():
    chunks = chunk_policy_text(read_policy_pdf(str(POLICY_PDF)))
    assert len(chunks) == 7
    titles = [c["title"] for c in chunks]
    assert "Waiting Period" in titles
    assert "Exclusions" in titles


@pytest.fixture(scope="module")
def policy_store(tmp_path_factory):
    from agents.policy_rag import ingest

    persist = tmp_path_factory.mktemp("chroma")
    count = ingest(str(POLICY_PDF), str(persist))
    return str(persist), count


def test_policy_ingestion_stores_all_sections(policy_store):
    _, count = policy_store
    assert count == 7


@pytest.mark.parametrize("question,expected_title", [
    ("How long is the waiting period?", "Waiting Period"),
    ("Which procedures are excluded as cosmetic?", "Exclusions"),
    ("What is the maximum payable amount per claim?", "Coverage Limit"),
])
def test_policy_retrieval_returns_relevant_section(policy_store, question, expected_title):
    from agents.policy_rag import query

    persist, _ = policy_store
    top = query(question, persist, k=1)[0]
    assert top["title"] == expected_title
