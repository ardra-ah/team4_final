"""LangGraph workflow for the Healthcare Insurance Claim Review Assistant.

Flow:
  ocr (retry) -> extract -> [policy, fraud] (parallel) -> router
    router -> investigation (high risk) -> recommendation
    router -> recommendation (approval, rejection review, clarification)
  recommendation -> human approval (interrupt, waits for a reviewer)
  ocr failure after retries -> escalate (ESCALATED)

No network calls are made here. Explanations use a template; the Gemini
hook is added later (Day 3 / follow-up) and runs on the user's machine.
"""

import operator
import sys
import time
from datetime import date
from pathlib import Path
from typing import Annotated, List, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from agents import rules  # noqa: E402
from agents.extraction import extract_claim  # noqa: E402
from agents.llm import explain  # noqa: E402
from agents.ocr import extract_text  # noqa: E402
from app.schemas import Decision  # noqa: E402

MAX_OCR_ATTEMPTS = 3


class ClaimState(TypedDict, total=False):
    # Inputs
    claim_id: str
    pdf_path: str
    claim_history: list
    policy_store: Optional[str]
    retry_backoff_s: float
    # Working data
    raw_text: str
    source_format: str
    extraction: dict
    policy_valid: bool
    policy_reasons: List[str]
    policy_evidence: List[str]
    duplicate_of: List[str]
    abnormal_reason: Optional[str]
    risk_level: str
    route: str
    investigation_report: Optional[str]
    recommended_decision: str
    explanation: str
    final_decision: str
    reviewer_note: str
    error: Optional[str]
    audit: Annotated[list, operator.add]


def _with_dates(extraction: dict) -> dict:
    ext = dict(extraction)
    if isinstance(ext.get("service_date"), str):
        ext["service_date"] = date.fromisoformat(ext["service_date"])
    return ext


def ocr_node(state: ClaimState) -> dict:
    backoff = state.get("retry_backoff_s", 0.5)
    last_error = None
    for attempt in range(1, MAX_OCR_ATTEMPTS + 1):
        try:
            raw, fmt = extract_text(state["pdf_path"])
            return {
                "raw_text": raw,
                "source_format": fmt,
                "audit": [f"ocr: ok on attempt {attempt} ({fmt})"],
            }
        except Exception as exc:  # noqa: BLE001 - any OCR failure is retried
            last_error = exc
            if attempt < MAX_OCR_ATTEMPTS:
                time.sleep(backoff * (2 ** (attempt - 1)))
    return {
        "error": f"OCR failed after {MAX_OCR_ATTEMPTS} attempts: {last_error}",
        "audit": [f"ocr: failed after {MAX_OCR_ATTEMPTS} attempts"],
    }


def extract_node(state: ClaimState) -> dict:
    claim = extract_claim(state["raw_text"], state.get("source_format", "text_pdf"))
    data = claim.model_dump(mode="json")
    return {"extraction": data, "audit": [f"extract: missing={data['missing_fields']}"]}


def policy_node(state: ClaimState) -> dict:
    ext = _with_dates(state["extraction"])
    valid, reasons = rules.policy_check(ext)
    evidence: List[str] = []
    if reasons and state.get("policy_store"):
        from agents.policy_rag import query

        for reason in reasons:
            hit = query(reason, state["policy_store"], k=1)[0]
            evidence.append(f"Section {hit['section']}: {hit['title']}")
    return {
        "policy_valid": valid,
        "policy_reasons": reasons,
        "policy_evidence": evidence,
        "audit": [f"policy: valid={valid}"],
    }


def fraud_node(state: ClaimState) -> dict:
    ext = _with_dates(state["extraction"])
    dups = rules.find_duplicates(ext, state.get("claim_history", []))
    abnormal = rules.abnormal_amount(ext)
    risk = "high" if (dups or abnormal) else "low"
    return {
        "duplicate_of": dups,
        "abnormal_reason": abnormal,
        "risk_level": risk,
        "audit": [f"fraud: risk={risk}"],
    }


def router_node(state: ClaimState) -> dict:
    """Order matters: missing data first, then fraud, then policy."""
    if state["extraction"].get("missing_fields"):
        route = "clarification"
    elif state.get("risk_level") == "high":
        route = "investigation"
    elif not state.get("policy_valid", True):
        route = "rejection_review"
    else:
        route = "approval"
    return {"route": route, "audit": [f"router: {route}"]}


def route_after_router(state: ClaimState) -> str:
    return {
        "approval": "recommendation",
        "rejection_review": "recommendation",
        "clarification": "recommendation",
        "investigation": "investigation",
    }[state["route"]]


def investigation_node(state: ClaimState) -> dict:
    parts = []
    if state.get("duplicate_of"):
        parts.append(f"Duplicate of existing claim(s): {', '.join(state['duplicate_of'])}.")
    if state.get("abnormal_reason"):
        parts.append(state["abnormal_reason"])
    report = " ".join(parts) or "No investigation findings."
    return {"investigation_report": report, "audit": ["investigation: report written"]}


_DECISION_BY_ROUTE = {
    "approval": Decision.APPROVED,
    "rejection_review": Decision.REJECTED,
    "clarification": Decision.PENDING_DOCUMENTS,
    "investigation": Decision.ESCALATED,
}


def recommendation_node(state: ClaimState) -> dict:
    route = state["route"]
    decision = _DECISION_BY_ROUTE[route]
    points: List[str] = []
    ext = state["extraction"]
    if ext.get("missing_fields"):
        points.append(f"Missing required fields: {', '.join(ext['missing_fields'])}.")
    points.extend(state.get("policy_reasons", []))
    if state.get("investigation_report"):
        points.append(state["investigation_report"])
    if not points:
        points.append("All coverage checks passed and no fraud indicators were found.")
    explanation = " ".join(points)
    facts = {
        "Claim ID": ext.get("claim_id"),
        "Route": route,
        "Decision": decision.value,
        "Missing fields": ", ".join(ext.get("missing_fields") or []) or "none",
        "Policy reasons": "; ".join(state.get("policy_reasons") or []) or "none",
        "Duplicate of": ", ".join(state.get("duplicate_of") or []) or "none",
        "Abnormal amount": state.get("abnormal_reason") or "none",
    }
    llm_text = explain(facts)
    source = "gemini" if llm_text else "template"
    if llm_text:
        explanation = llm_text
    return {
        "recommended_decision": decision.value,
        "explanation": explanation,
        "audit": [f"recommendation: {decision.value} (explanation: {source})"],
    }


def human_node(state: ClaimState) -> dict:
    """Pause for a claims officer. Resume with a Decision value or nothing."""
    reviewer_input = interrupt({
        "claim_id": state.get("claim_id"),
        "recommended_decision": state["recommended_decision"],
        "explanation": state["explanation"],
        "allowed": [d.value for d in Decision],
    })
    valid = {d.value for d in Decision}
    if isinstance(reviewer_input, dict):
        chosen = reviewer_input.get("decision")
        note = reviewer_input.get("note", "")
    else:
        chosen, note = reviewer_input, ""
    final = chosen if chosen in valid else state["recommended_decision"]
    return {
        "final_decision": final,
        "reviewer_note": note,
        "audit": [f"human: final={final}"],
    }


def escalate_node(state: ClaimState) -> dict:
    return {
        "final_decision": Decision.ESCALATED.value,
        "reviewer_note": state.get("error", ""),
        "audit": ["escalate: sent to manual queue"],
    }


def route_after_ocr(state: ClaimState) -> str:
    return "escalate" if state.get("error") else "extract"


def build_graph():
    g = StateGraph(ClaimState)
    g.add_node("ocr", ocr_node)
    g.add_node("extract", extract_node)
    g.add_node("policy", policy_node)
    g.add_node("fraud", fraud_node)
    g.add_node("router", router_node)
    g.add_node("investigation", investigation_node)
    g.add_node("recommendation", recommendation_node)
    g.add_node("human", human_node)
    g.add_node("escalate", escalate_node)

    g.add_edge(START, "ocr")
    g.add_conditional_edges("ocr", route_after_ocr, {"extract": "extract", "escalate": "escalate"})
    g.add_edge("extract", "policy")
    g.add_edge("extract", "fraud")
    g.add_edge("policy", "router")
    g.add_edge("fraud", "router")
    g.add_conditional_edges("router", route_after_router, {
        "recommendation": "recommendation",
        "investigation": "investigation",
    })
    g.add_edge("investigation", "recommendation")
    g.add_edge("recommendation", "human")
    g.add_edge("human", END)
    g.add_edge("escalate", END)
    return g.compile(checkpointer=MemorySaver())


def run_claim(app, thread_id: str, inputs: dict) -> dict:
    """Start a claim. Returns the state, or the pending interrupt if waiting for review."""
    config = {"configurable": {"thread_id": thread_id}}
    return app.invoke(inputs, config)


def resume_claim(app, thread_id: str, decision: str, note: str = "") -> dict:
    """Resume a paused claim with the reviewer's decision."""
    from langgraph.types import Command

    config = {"configurable": {"thread_id": thread_id}}
    return app.invoke(Command(resume={"decision": decision, "note": note}), config)
