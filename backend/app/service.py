"""Claim service: runs the LangGraph workflow for uploaded claims and tracks runs.

Settings come from environment variables:
  DATABASE_URL       PostgreSQL connection string. Claim history is read from it, and
                     review runs are saved to the review_runs table so they survive restarts.
  UPLOAD_DIR         where uploaded PDFs are stored (default: data/uploads)
  POLICY_STORE_DIR   ChromaDB folder for policy text (default: data/chroma)

If the database is unreachable, uploads still work: history falls back to seed data and
runs are kept in memory only, with a warning in the API log.
"""

import hashlib
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agents.policy_rag import ingest  # noqa: E402
from agents.workflow import build_graph, resume_claim, run_claim  # noqa: E402
from app.schemas import Decision  # noqa: E402

POLICY_PDF = ROOT / "data" / "policies" / "policy_guidelines.pdf"
log = logging.getLogger(__name__)

# Used when the database is not reachable. Matches the one history row in data/db/seed.sql.
SEED_HISTORY = [{
    "claim_id": "CLM-2026-HIST-001",
    "member_id": "MBR-99901",
    "policy_number": "POL-HC-5599",
    "provider_id": "PRV-0042",
    "service_date": "2026-08-14",
    "procedure_code": "99213",
    "billed_amount": 180.0,
    "claimed_amount": 180.0,
}]

REVIEW_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS review_runs (
    run_id          VARCHAR(40) PRIMARY KEY,
    filename        VARCHAR(255) NOT NULL,
    claim_id        VARCHAR(40),
    status          VARCHAR(30) NOT NULL,
    final_decision  VARCHAR(30),
    created_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    summary         JSONB NOT NULL
)
"""


def load_history() -> List[dict]:
    """Claim history for duplicate checks: PostgreSQL when DATABASE_URL is set, seed data otherwise."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return list(SEED_HISTORY)
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT claim_id, member_id, policy_number, provider_id, service_date, "
                "procedure_code, billed_amount, claimed_amount FROM claims_history"
            )
            cols = [c.name for c in cur.description]
            rows = []
            for row in cur.fetchall():
                item = dict(zip(cols, row))
                item["service_date"] = item["service_date"].isoformat()
                item["billed_amount"] = float(item["billed_amount"])
                item["claimed_amount"] = float(item["claimed_amount"])
                rows.append(item)
            return rows
    except Exception as exc:  # noqa: BLE001 - any DB failure falls back to seed data
        log.warning("Database unreachable, using seed history instead: %s", exc)
        return list(SEED_HISTORY)


def describe_claim(ext: dict) -> str:
    """Plain-English summary built from the extracted fields.

    Member names and member IDs are deliberately left out.
    """
    if not ext:
        return "No structured data could be extracted from this document."
    head = f"Claim {ext['claim_id']}" if ext.get("claim_id") else "Claim"
    if ext.get("provider_name"):
        head += f" from {ext['provider_name']}"
    parts = [head + "."]

    details = []
    if ext.get("procedure_code"):
        details.append(f"procedure {ext['procedure_code']}")
    if ext.get("diagnosis_code"):
        details.append(f"diagnosis {ext['diagnosis_code']}")
    if ext.get("service_date"):
        details.append(f"service date {ext['service_date']}")
    if details:
        parts.append("Services: " + ", ".join(details) + ".")

    amount = ext.get("billed_amount")
    if amount is not None:
        parts.append(f"Billed {ext.get('currency') or 'USD'} {float(amount):,.2f}.")

    docs = ext.get("documents_attached") or []
    if docs:
        parts.append(f"{len(docs)} supporting document(s) attached.")

    missing = ext.get("missing_fields") or []
    parts.append("Missing fields: " + (", ".join(missing) if missing else "none") + ".")
    return " ".join(parts)


class RunStore:
    """Saves review run summaries to PostgreSQL. Disabled when no URL is given."""

    def __init__(self, url: Optional[str]):
        self.url = url
        self.enabled = False
        if not url:
            return
        try:
            import psycopg

            with psycopg.connect(url, connect_timeout=5) as conn:
                conn.execute(REVIEW_RUNS_DDL)
            self.enabled = True
        except Exception as exc:  # noqa: BLE001
            log.warning("Run storage unavailable, runs will not survive a restart: %s", exc)

    def save(self, summary: dict) -> None:
        if not self.enabled:
            return
        try:
            import psycopg
            from psycopg.types.json import Jsonb

            with psycopg.connect(self.url, connect_timeout=5) as conn:
                conn.execute(
                    """
                    INSERT INTO review_runs
                        (run_id, filename, claim_id, status, final_decision, created_at, updated_at, summary)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
                    ON CONFLICT (run_id) DO UPDATE SET
                        claim_id       = EXCLUDED.claim_id,
                        status         = EXCLUDED.status,
                        final_decision = EXCLUDED.final_decision,
                        updated_at     = NOW(),
                        summary        = EXCLUDED.summary
                    """,
                    (
                        summary["run_id"],
                        summary["filename"],
                        summary["claim_id"],
                        summary["status"],
                        summary["final_decision"],
                        summary["created_at"],
                        Jsonb(summary),
                    ),
                )
        except Exception as exc:  # noqa: BLE001 - a storage failure must not fail the claim
            log.warning("Could not save review run %s: %s", summary.get("run_id"), exc)

    def load_all(self) -> List[dict]:
        if not self.enabled:
            return []
        try:
            import psycopg

            with psycopg.connect(self.url, connect_timeout=5) as conn:
                rows = conn.execute("SELECT summary FROM review_runs ORDER BY created_at").fetchall()
            return [row[0] for row in rows]
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load saved review runs: %s", exc)
            return []


    def delete(self, run_id: str) -> None:
        if not self.enabled:
            return
        try:
            import psycopg

            with psycopg.connect(self.url, connect_timeout=5) as conn:
                conn.execute("DELETE FROM review_runs WHERE run_id = %s", (run_id,))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not delete saved review run %s: %s", run_id, exc)


class DuplicateUploadError(ValueError):
    """The uploaded file is identical to a claim that is still open for review."""


def _history_entry(extraction: dict) -> dict:
    """Turn a saved extraction into a claims_history-style row for the duplicate check."""
    return {
        "claim_id": extraction.get("claim_id"),
        "member_id": extraction.get("member_id"),
        "policy_number": extraction.get("policy_number"),
        "provider_id": extraction.get("provider_id"),
        "service_date": extraction.get("service_date"),
        "procedure_code": extraction.get("procedure_code"),
        "billed_amount": extraction.get("billed_amount"),
        "claimed_amount": extraction.get("claimed_amount"),
    }


class ClaimService:
    def __init__(
        self,
        upload_dir: Path,
        policy_store: Path,
        history_loader=load_history,
        retry_backoff_s: float = 0.5,
        run_store: Optional[RunStore] = None,
    ):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.policy_store = Path(policy_store)
        self.policy_store.mkdir(parents=True, exist_ok=True)
        ingest(str(POLICY_PDF), str(self.policy_store))
        self.history_loader = history_loader
        self.retry_backoff_s = retry_backoff_s
        self.graph = build_graph()
        self.run_store = run_store or RunStore(None)

        # Each run has either a live workflow state (state is set) or a saved record
        # (state is None), which is what we reload after a restart.
        self.runs: Dict[str, dict] = {}
        for record in self.run_store.load_all():
            self.runs[record["run_id"]] = {
                "run_id": record["run_id"],
                "filename": record["filename"],
                "created_at": record["created_at"],
                "parent_run_id": record.get("parent_run_id"),
                "processing_ms": record.get("processing_ms"),
                "content_hash": record.get("content_hash"),
                "state": None,
                "record": record,
            }

    # ----- public API -------------------------------------------------------

    def submit(self, filename: str, content: bytes, parent_run_id: Optional[str] = None) -> dict:
        digest = hashlib.sha256(content).hexdigest()
        identical = [r for r in self.runs.values() if r.get("content_hash") == digest]

        open_run = next((r["run_id"] for r in identical if self._is_open(r["run_id"])), None)
        if open_run:
            raise DuplicateUploadError(
                f"This document is already in review (run {open_run}). "
                "Open that claim instead of uploading it again."
            )

        history = list(self.history_loader())
        decided = next((r for r in identical if r.get("content_hash") == digest), None)
        if decided:
            # An identical file that was already decided is checked against the workflow
            # as history, so the existing duplicate rule flags it for investigation.
            extraction = self.summary(decided["run_id"]).get("extraction") or {}
            if extraction.get("claim_id"):
                history.append(_history_entry(extraction))

        run_id = uuid.uuid4().hex
        pdf_path = self.upload_dir / f"{run_id}.pdf"
        pdf_path.write_bytes(content)
        started = time.perf_counter()
        state = run_claim(self.graph, run_id, {
            "claim_id": run_id,
            "pdf_path": str(pdf_path),
            "claim_history": history,
            "policy_store": str(self.policy_store),
            "retry_backoff_s": self.retry_backoff_s,
        })
        self.runs[run_id] = {
            "run_id": run_id,
            "filename": filename,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "parent_run_id": parent_run_id,
            "processing_ms": round((time.perf_counter() - started) * 1000),
            "content_hash": digest,
            "state": state,
            "record": None,
        }
        self._save(run_id)
        return self.summary(run_id)

    def resubmit(self, parent_run_id: str, filename: str, content: bytes) -> dict:
        """Submit corrected or missing documents for a claim where documents were requested."""
        parent = self.summary(parent_run_id)  # raises KeyError if unknown
        if parent["final_decision"] != "PENDING_DOCUMENTS":
            raise ValueError("Only claims where documents were requested can be resubmitted.")
        if parent["resubmitted_as"]:
            raise ValueError("This claim has already been resubmitted.")
        return self.submit(filename, content, parent_run_id=parent_run_id)

    def decide(self, run_id: str, decision: Decision, note: str = "") -> dict:
        run = self._get_run(run_id)
        current = self.summary(run_id)
        if current["final_decision"]:
            raise ValueError("claim already has a final decision")
        if current["status"] != "awaiting_review":
            raise ValueError("claim is not waiting for review")

        if run["state"] is not None:
            run["state"] = resume_claim(self.graph, run_id, decision.value, note)
        else:
            # The paused workflow was lost when the server restarted, so record the
            # reviewer's decision directly and say so in the audit trail.
            record = dict(run["record"])
            record["final_decision"] = decision.value
            record["reviewer_note"] = note
            record["status"] = "completed"
            record["audit"] = list(record.get("audit", [])) + [
                f"human: final={decision.value} (recorded after restart)"
            ]
            run["record"] = record
        self._save(run_id)
        return self.summary(run_id)

    def summary(self, run_id: str) -> dict:
        run = self._get_run(run_id)
        data = dict(run["record"]) if run["state"] is None else self._live_summary(run_id, run)
        data["parent_run_id"] = run.get("parent_run_id")
        data["processing_ms"] = run.get("processing_ms")
        data["resubmitted_as"] = self._child_of(run_id)
        data["content_hash"] = run.get("content_hash")
        return data

    def delete(self, run_id: str) -> None:
        """Remove a review run: its audit trail, its stored PDF, and its saved record.

        Reference data (claims_history) is not touched, so duplicate checks are unaffected.
        """
        self._get_run(run_id)  # raises KeyError if unknown
        # A resubmission that pointed at this run must not link to a missing claim.
        for other in self.runs.values():
            if other.get("parent_run_id") == run_id:
                other["parent_run_id"] = None
                self._save(other["run_id"])
        del self.runs[run_id]
        self.run_store.delete(run_id)
        try:
            (self.upload_dir / f"{run_id}.pdf").unlink()
        except FileNotFoundError:
            pass

    def list_runs(self) -> List[dict]:
        return [self.summary(run_id) for run_id in self.runs]

    # ----- helpers ----------------------------------------------------------

    def _live_summary(self, run_id: str, run: dict) -> dict:
        s = run["state"]
        ext = s.get("extraction") or {}
        waiting = "__interrupt__" in s and not s.get("final_decision")
        return {
            "run_id": run_id,
            "filename": run["filename"],
            "created_at": run["created_at"],
            "status": "awaiting_review" if waiting else "completed",
            "claim_id": ext.get("claim_id"),
            "claim_summary": describe_claim(ext),
            "route": s.get("route"),
            "recommended_decision": s.get("recommended_decision"),
            "explanation": s.get("explanation"),
            "final_decision": s.get("final_decision"),
            "reviewer_note": s.get("reviewer_note"),
            "missing_fields": ext.get("missing_fields", []),
            "policy_reasons": s.get("policy_reasons", []),
            "policy_evidence": s.get("policy_evidence", []),
            "duplicate_of": s.get("duplicate_of", []),
            "risk_level": s.get("risk_level"),
            "error": s.get("error"),
            "audit": s.get("audit", []),
            "extraction": ext,
        }

    def _child_of(self, run_id: str) -> Optional[str]:
        return next((rid for rid, r in self.runs.items() if r.get("parent_run_id") == run_id), None)

    def _is_open(self, run_id: str) -> bool:
        """A run is open while a reviewer must act: awaiting review, or waiting for documents."""
        s = self.summary(run_id)
        if s["status"] == "awaiting_review":
            return True
        return s["final_decision"] == "PENDING_DOCUMENTS" and not s["resubmitted_as"]

    def _save(self, run_id: str) -> None:
        self.run_store.save(self.summary(run_id))

    def _get_run(self, run_id: str) -> dict:
        if run_id not in self.runs:
            raise KeyError(run_id)
        return self.runs[run_id]
