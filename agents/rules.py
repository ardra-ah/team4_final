"""Deterministic policy and fraud rules for the synthetic claim workflow.

These values mirror the policy guidelines PDF (data/generator/generate_claims.py).
They are the source of truth for the rule checks; the RAG store supplies the
explanatory policy text as evidence.
"""

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

CLAIM_LIMIT_USD = 5000.00
POLICY_EFFECTIVE = date(2026, 8, 1)
WAITING_PERIOD_DAYS = 30
EXCLUDED_PROCEDURES = {"15820", "15821"}  # cosmetic procedures
REQUIRED_FIELDS = [
    "claim_id", "member_id", "policy_number", "service_date",
    "diagnosis_code", "procedure_code", "billed_amount", "claimed_amount",
]

# Typical billed rate per procedure (USD). Used by the abnormal-amount rule.
TYPICAL_RATES_USD: Dict[str, float] = {
    "99213": 180.00,
    "80053": 120.00,
    "71046": 150.00,
}
ABNORMAL_MULTIPLIER = 10


def policy_check(extraction: dict) -> Tuple[bool, List[str]]:
    """Return (coverage_valid, reasons). Reasons explain every failed rule."""
    reasons: List[str] = []
    service_date = extraction.get("service_date")
    if service_date:
        waiting_end = POLICY_EFFECTIVE + timedelta(days=WAITING_PERIOD_DAYS)
        if service_date < waiting_end:
            reasons.append(
                f"Service date {service_date} is inside the {WAITING_PERIOD_DAYS}-day waiting period "
                f"(ends {waiting_end})."
            )
    if extraction.get("procedure_code") in EXCLUDED_PROCEDURES:
        reasons.append(f"Procedure {extraction['procedure_code']} is an excluded cosmetic procedure.")
    claimed = extraction.get("claimed_amount")
    billed = extraction.get("billed_amount")
    if claimed is not None and claimed > CLAIM_LIMIT_USD:
        reasons.append(f"Claimed amount {claimed:.2f} exceeds the {CLAIM_LIMIT_USD:.2f} limit.")
    if claimed is not None and billed is not None and claimed > billed:
        reasons.append(f"Claimed amount {claimed:.2f} is more than the billed amount {billed:.2f}.")
    return (len(reasons) == 0), reasons


def currency_issue(extraction: dict) -> Optional[str]:
    """Claims are only handled in USD. Anything else needs a person to check it."""
    currency = (extraction.get("currency") or "USD").upper()
    if currency != "USD":
        return f"The claim amounts are in {currency}, not USD. A person needs to check the currency before any payment."
    return None


def find_duplicates(extraction: dict, history: List[dict]) -> List[str]:
    """A duplicate matches member, provider, service date, and procedure."""
    matches = []
    for h in history:
        if (
            h.get("member_id") == extraction.get("member_id")
            and h.get("provider_id") == extraction.get("provider_id")
            and str(h.get("service_date")) == str(extraction.get("service_date"))
            and h.get("procedure_code") == extraction.get("procedure_code")
        ):
            matches.append(h["claim_id"])
    return matches


def abnormal_amount(extraction: dict) -> Optional[str]:
    """Return a reason if the billed amount is far above the typical rate."""
    code = extraction.get("procedure_code")
    billed = extraction.get("billed_amount")
    typical = TYPICAL_RATES_USD.get(code)
    if typical and billed and billed > typical * ABNORMAL_MULTIPLIER:
        return (
            f"Billed {billed:.2f} is {billed / typical:.1f}x the typical rate "
            f"for {code} ({typical:.2f})."
        )
    return None
