# Phase 3 Results: LangGraph Workflow

## What was built
- `agents/rules.py`: deterministic policy rules (coverage limit, waiting period, cosmetic exclusions), duplicate detection, and abnormal-amount detection.
- `agents/workflow.py`: LangGraph graph with OCR retries, extraction, parallel policy and fraud checks, a router with four paths, investigation, recommendation, human approval (interrupt and resume), and escalation on OCR failure. Explanations use a template. No network calls.
- `tests/test_workflow.py`: 46 offline tests.

## Routing order
1. Missing required fields → clarification
2. High fraud risk (duplicate or abnormal amount) → investigation
3. Policy check failed → rejection review
4. Otherwise → approval

## Results
- `pytest tests/ -q`: 77 passed (31 Day 1 + 46 Phase 3).
- All 20 labeled claims route to the expected path and produce the expected decision after review.

## Limits to keep in mind
- The synthetic labels were written alongside these rules, so a full match shows the implementation follows the spec. It does not show accuracy on real claims.
- The Gemini-based explanation step is not implemented yet. It will run on the user's machine because the sandbox cannot reach the Gemini API.
- Duplicate detection reads `claim_history` passed in as input. Loading it from Neon is part of Day 3 (API layer).
- The clarification loop (documents received → re-enter upload) is not wired yet. It belongs to the Day 3 API.
