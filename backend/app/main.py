"""FastAPI app for the Healthcare Insurance Claim Review Assistant.

Run from the project root:
    uvicorn app.main:app --app-dir backend --reload
Then open http://127.0.0.1:8000/docs
"""

import os
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, HTTPException, Response, UploadFile  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.schemas import Decision  # noqa: E402
from app.service import ClaimService, DuplicateUploadError, RunStore  # noqa: E402


class DecisionIn(BaseModel):
    decision: Decision
    note: Optional[str] = ""


# Member identifiers stay inside the server (duplicate checks need them) and are
# removed from every response the API sends back to the screen or to other programs.
HIDDEN_EXTRACTION_FIELDS = ("member_id", "member_name")


def public_view(summary: dict) -> dict:
    """Return a copy of a claim summary that is safe to send out of the API."""
    data = dict(summary)
    if isinstance(data.get("extraction"), dict):
        data["extraction"] = {
            k: v for k, v in data["extraction"].items() if k not in HIDDEN_EXTRACTION_FIELDS
        }
    return data


def create_app(service: Optional[ClaimService] = None) -> FastAPI:
    app = FastAPI(title="Healthcare Claim Review API", version="0.3.0")
    svc = service or ClaimService(
        upload_dir=Path(os.environ.get("UPLOAD_DIR", ROOT / "data" / "uploads")),
        policy_store=Path(os.environ.get("POLICY_STORE_DIR", ROOT / "data" / "chroma")),
        run_store=RunStore(os.environ.get("DATABASE_URL")),
    )
    app.state.service = svc

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/claims", status_code=201)
    async def submit_claim(file: UploadFile = File(...)):
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=422, detail="Only PDF claims are accepted.")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=422, detail="Uploaded file is empty.")
        try:
            return public_view(svc.submit(file.filename, content))
        except DuplicateUploadError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/claims/{run_id}/resubmit", status_code=201)
    async def resubmit_claim(run_id: str, file: UploadFile = File(...)):
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=422, detail="Only PDF claims are accepted.")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=422, detail="Uploaded file is empty.")
        try:
            return public_view(svc.resubmit(run_id, file.filename, content))
        except KeyError:
            raise HTTPException(status_code=404, detail="Claim not found.")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.get("/claims")
    def list_claims() -> List[dict]:
        return [public_view(s) for s in svc.list_runs()]

    @app.get("/claims/{run_id}")
    def get_claim(run_id: str):
        try:
            return public_view(svc.summary(run_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="Claim not found.")

    @app.delete("/claims/{run_id}", status_code=204)
    def delete_claim(run_id: str):
        try:
            svc.delete(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Claim not found.")
        return Response(status_code=204)

    @app.post("/claims/{run_id}/decision")
    def decide(run_id: str, body: DecisionIn):
        try:
            return public_view(svc.decide(run_id, body.decision, body.note or ""))
        except KeyError:
            raise HTTPException(status_code=404, detail="Claim not found.")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    return app


app = create_app()
