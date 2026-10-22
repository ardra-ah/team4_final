# Day 1 Results

## Phase 0: Setup and contracts
- Repo structure created (`backend/`, `agents/`, `data/`, `tests/`, `docs/`).
- Frozen contracts in `backend/app/schemas.py`: decision enum (APPROVED, REJECTED, PENDING_DOCUMENTS, ESCALATED), route enum (approval, investigation, clarification, rejection_review), claim extraction schema.
- `docker-compose.yml` defines Postgres and Chroma. Not started in this session (Docker daemon unavailable in the workspace).

## Phase 1: Synthetic data
- 20 fictional claim PDFs in `data/claims/`: 8 clean, 4 missing field, 4 policy violation, 2 duplicate, 2 high fraud.
- CLM-2026-0001 is a scanned image PDF to exercise the OCR fallback.
- `labels.json` holds ground-truth route and decision per claim.
- Policy guidelines PDF (7 numbered sections) in `data/policies/`.
- `data/db/schema.sql` and `seed.sql` for Postgres. SQL was generated but not executed against a live database.

## Phase 2: OCR, extraction, policy RAG
- OCR: PyMuPDF text layer, with Tesseract fallback for pages without text. Verified on the scanned claim.
- Extraction: deterministic label parsing into `ClaimExtraction`, with missing-field detection.
- Policy RAG: sections chunked and stored in ChromaDB. Embeddings use an offline hashed bag-of-words function because the sandbox blocks the default model download. Replace with Gemini embeddings when the API key is configured.

## Test results
`pytest tests/ -q` gives **31 passed**:
- Label coverage and enum checks (2)
- OCR text and scanned paths (2)
- Extraction matches ground truth for all 20 claims (20)
- Amount, date, and missing-diagnosis parsing (3)
- Policy chunking and ingestion (4 incl. 3 retrieval checks)

## Known gaps carried into Day 2
- Embeddings are offline placeholders, not semantic. Retrieval passed the three test queries, but Gemini embeddings should replace them before the demo.
- Postgres seed not yet run against a live database.
- LLM fallback for extraction is not implemented (not needed for the templated synthetic claims).
