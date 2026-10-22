# Healthcare Insurance Claim Review Assistant

A multi-agent claim review system built with LangGraph. It reads a claim PDF, extracts the fields, checks them against policy rules, screens for duplicates and unusual amounts, routes the claim, and asks a human reviewer for the final decision. Gemini writes a short plain-English explanation for the reviewer. The rules make the decision; the model never changes it.

**All data in this repository is synthetic.** No real patient records or government identifiers are used.

## What it does

- **Intake:** upload a text-layer or scanned claim PDF (RapidOCR handles scans, with retries and backoff).
- **Extraction:** pulls the claim ID, member, policy, provider, dates, codes, and amounts. Missing or blank required fields are listed.
- **Parallel checks:** a policy check (waiting period, excluded procedures, claim limit) and a fraud check (duplicates against history, abnormal amounts) run at the same time.
- **Routing:** missing fields go to clarification, high risk goes to investigation, policy failures go to rejection review, and everything else goes to approval.
- **Human decision:** every claim pauses for a reviewer. The reviewer can accept the recommendation or choose another outcome, with a note.
- **Duplicate uploads:** the same file cannot be uploaded again while it is still open. If the earlier claim was already decided, the new upload is flagged as a duplicate and sent to investigation.
- **Clarification loop:** when documents are missing, the claim waits for a resubmission, which is linked to the original.
- **Persistence:** review runs and audit trails are saved in PostgreSQL, so they survive a restart.
- **Observability:** each run records processing time and a full audit trail. Optional LangSmith tracing shows the agent steps.

## Architecture

```
PDF -> OCR (retry x3) -> extract -> [policy | fraud] -> router
                                                        |-> investigation (high risk) -> recommendation
                                                        |-> recommendation (approval, rejection review, clarification)
recommendation -> human review (pause) -> final decision
OCR failure after retries -> escalate
```

Policy questions are answered from a ChromaDB store built from the policy guidelines PDF. Gemini embeddings are used when enabled; an offline embedding is used otherwise or if Gemini fails.

## Project layout

| Path | Purpose |
|---|---|
| `backend/app/` | FastAPI app (`main.py`), claim service and run storage (`service.py`), shared schemas (`schemas.py`) |
| `agents/` | Workflow graph, OCR, extraction, rules, policy RAG, Gemini explanation step |
| `frontend/` | React + TypeScript review console (Vite) |
| `scripts/` | `start_api.py` (starts the API with `.env`), `run_all_claims.py` (runs the labeled claims) |
| `data/generator/` | Generators for the synthetic claims, policy PDF, labels, and seed SQL |
| `data/claims/` | Synthetic claim PDFs, `labels.json` (ground truth), and `DEMO_GUIDE.md` |
| `data/db/` | PostgreSQL schema and seed data |
| `tests/` | Offline tests for the API, workflow, deletion, duplicates, and embeddings |
| `docs/` | Architecture, demo script, and run results |

## Prerequisites

- Python 3.12 or newer
- Node.js 20 or newer (for the frontend)
- PostgreSQL 16 or newer, installed locally (Docker is not required)
- A Gemini API key from Google AI Studio (optional; the app works without it)

## Setup

Run these in PowerShell from the project folder.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

Create the database once, using pgAdmin or `psql`:

```sql
CREATE DATABASE claim_review;
```

Then load the schema and seed data:

```powershell
psql -U postgres -d claim_review -f data\db\schema.sql
psql -U postgres -d claim_review -f data\db\seed.sql
```

Create your settings file by copying the example, then edit `.env` with your own values:

```powershell
copy .env.example .env
```

`.env` holds secrets and is ignored by git. Never commit it.

## Run

Use two terminals.

```powershell
# Terminal 1: API on http://127.0.0.1:8000 (API docs at /docs)
.\.venv\Scripts\Activate.ps1
python scripts\start_api.py

# Terminal 2: review console on http://localhost:5173
cd frontend
npm run dev
```

Open http://localhost:5173 and upload a claim from `data\claims`. Start with `demo01_complete_approve.pdf`. `data\claims\DEMO_GUIDE.md` lists the demo files and what each one should produce.

## Tests

```powershell
pytest -q
```

The tests run offline. They do not need PostgreSQL, Gemini, or LangSmith.

To run the 20 labeled claims against a running API and compare with the ground truth:

```powershell
python scripts\run_all_claims.py
```

Results are written to `docs/claim_run_results.csv`.

## Settings

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | No | PostgreSQL connection. Without it, runs are kept in memory and history uses seed data. |
| `LLM_ENABLED` | No | Set to `1` to enable Gemini explanations and Gemini policy embeddings. |
| `GEMINI_API_KEY` | With `LLM_ENABLED=1` | Key from Google AI Studio. |
| `GEMINI_MODEL` | No | Gemini model for explanations. Set it to a model your key can use. |
| `POLICY_EMBEDDINGS` | No | Set to `local` to always use the offline policy embeddings. |
| `GEMINI_EMBED_MODEL` | No | Embedding model (default `gemini-embedding-001`). |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | No | Send workflow traces to LangSmith. |
| `UPLOAD_DIR`, `POLICY_STORE_DIR` | No | Override where uploads and the policy vector store are kept. |

Values set in the terminal take priority over `.env`. Changes to `.env` apply after the API is restarted.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/claims` | Upload a claim PDF. Returns 409 if the same file is still open. |
| GET | `/claims` | List all review runs |
| GET | `/claims/{run_id}` | One run with its audit trail |
| POST | `/claims/{run_id}/decision` | Record the reviewer's decision and note |
| POST | `/claims/{run_id}/resubmit` | Upload missing documents for a claim waiting on them |
| DELETE | `/claims/{run_id}` | Delete a run, its audit trail, and its stored PDF |

## Decisions

The workflow can only produce `APPROVED`, `REJECTED`, `PENDING_DOCUMENTS`, or `ESCALATED`.

## Known limitations

- The synthetic labels were generated with the same rules the system uses, so 20 of 20 matching shows consistency, not accuracy on real claims.
- A claim paused for review when the server restarts can still be decided, but the paused workflow itself is lost. The decision is recorded with a note in the audit trail.
- Duplicate detection matches on member, provider, service date, and procedure code, using the seeded history plus earlier runs that are identical files.
- This is a demonstration system. It is not validated for use with real claims or real patient data.
