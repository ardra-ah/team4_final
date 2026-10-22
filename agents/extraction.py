"""Claim Extraction Agent: raw OCR text -> structured ClaimExtraction JSON.

Claims use a fixed "Label: value" layout, so extraction is deterministic
(regex). An LLM fallback (Gemini) can be added later for free-form documents.
"""

import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.schemas import ClaimExtraction  # noqa: E402

REQUIRED_FIELDS = [
    "claim_id",
    "member_id",
    "policy_number",
    "service_date",
    "diagnosis_code",
    "procedure_code",
    "billed_amount",
    "claimed_amount",
]

LABEL_TO_FIELD = {
    "Claim ID": "claim_id",
    "Member ID": "member_id",
    "Policy Number": "policy_number",
    "Member Name": "member_name",
    "Provider ID": "provider_id",
    "Provider Name": "provider_name",
    "Service Date": "service_date",
    "Diagnosis Code": "diagnosis_code",
    "Procedure Code": "procedure_code",
    "Billed Amount": "billed_amount",
    "Claimed Amount": "claimed_amount",
    "Documents Attached": "documents_attached",
}

_LINE = re.compile(r"^\s*([A-Za-z ]+?)\s*:\s*(.+?)\s*$", re.MULTILINE)
_AMOUNT = re.compile(r"(\d[\d,]*\.\d{2})")
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_ICD = re.compile(r"\b([A-Z]\d{2}(?:\.\w{1,4})?)\b")
_CPT = re.compile(r"\b(\d{5})\b")


def _normalize_label(label: str) -> str:
    """OCR can drop spaces or change capitals ('SerViceDate'), so compare letters only."""
    return re.sub(r"[^a-z]", "", label.lower())


_NORMALIZED_LABELS = {_normalize_label(k): v for k, v in LABEL_TO_FIELD.items()}


def _parse_pairs(raw_text: str) -> Dict[str, str]:
    pairs: Dict[str, str] = {}
    for match in _LINE.finditer(raw_text):
        key = _normalize_label(match.group(1))
        value = match.group(2).strip()
        if key in _NORMALIZED_LABELS and _NORMALIZED_LABELS[key] not in pairs:
            pairs[_NORMALIZED_LABELS[key]] = value
    return pairs


def _amount(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    m = _AMOUNT.search(value)
    return float(m.group(1).replace(",", "")) if m else None


def _date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    m = _DATE.search(value)
    return date.fromisoformat(m.group(1)) if m else None


def extract_claim(raw_text: str, source_format: str = "text_pdf") -> ClaimExtraction:
    pairs = _parse_pairs(raw_text)

    diagnosis = None
    if "diagnosis_code" in pairs:
        m = _ICD.search(pairs["diagnosis_code"])
        diagnosis = m.group(1) if m else None

    procedure = None
    if "procedure_code" in pairs:
        m = _CPT.search(pairs["procedure_code"])
        procedure = m.group(1) if m else None

    docs_raw = pairs.get("documents_attached", "")
    documents = [] if docs_raw.strip().lower() in ("", "none") else [
        d.strip() for d in docs_raw.split(",") if d.strip()
    ]

    data = {
        "claim_id": pairs.get("claim_id"),
        "member_id": pairs.get("member_id"),
        "policy_number": pairs.get("policy_number"),
        "member_name": pairs.get("member_name"),
        "provider_id": pairs.get("provider_id"),
        "provider_name": pairs.get("provider_name"),
        "service_date": _date(pairs.get("service_date")),
        "diagnosis_code": diagnosis,
        "procedure_code": procedure,
        "billed_amount": _amount(pairs.get("billed_amount")),
        "claimed_amount": _amount(pairs.get("claimed_amount")),
        "documents_attached": documents,
        "source_format": source_format,
    }

    missing = [f for f in REQUIRED_FIELDS if data.get(f) in (None, "")]
    data["missing_fields"] = missing
    return ClaimExtraction(**data)
