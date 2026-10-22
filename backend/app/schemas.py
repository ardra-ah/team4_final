"""Shared contracts for the Healthcare Insurance Claim Review Assistant.

These are frozen in Phase 0. Every agent, the API, and the UI import from here.
All data is synthetic.
"""

from datetime import date
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Decision(str, Enum):
    """The only outcomes the workflow may emit."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING_DOCUMENTS = "PENDING_DOCUMENTS"
    ESCALATED = "ESCALATED"


class RoutePath(str, Enum):
    """Router Agent outcomes."""

    APPROVAL = "approval"
    INVESTIGATION = "investigation"
    CLARIFICATION = "clarification"
    REJECTION_REVIEW = "rejection_review"


class ClaimExtraction(BaseModel):
    """Structured output of the Claim Extraction Agent."""

    claim_id: Optional[str] = None
    member_id: Optional[str] = None
    policy_number: Optional[str] = None
    member_name: Optional[str] = None
    provider_id: Optional[str] = None
    provider_name: Optional[str] = None
    service_date: Optional[date] = None
    diagnosis_code: Optional[str] = None
    procedure_code: Optional[str] = None
    billed_amount: Optional[float] = None
    claimed_amount: Optional[float] = None
    currency: str = "USD"
    documents_attached: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    source_format: str = Field(
        default="text_pdf",
        description="text_pdf | scanned_pdf | image",
    )


class ClaimLabel(BaseModel):
    """Ground-truth label for a synthetic claim. Used only by tests."""

    claim_id: str
    scenario: str
    expected_path: RoutePath
    expected_decision: Decision
    expected_missing_fields: List[str] = Field(default_factory=list)
