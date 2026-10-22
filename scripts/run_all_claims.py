"""Upload all 20 synthetic claims to the running API, accept each recommendation,
and compare the result with data/claims/labels.json.

Start the API first (from the project folder):
    uvicorn app.main:app --app-dir backend --port 8000
Then run:
    python scripts/run_all_claims.py
Results are printed and saved to docs/claim_run_results.csv.
"""

import csv
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CLAIMS_DIR = ROOT / "data" / "claims"
RESULTS = ROOT / "docs" / "claim_run_results.csv"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def main() -> int:
    labels = json.loads((CLAIMS_DIR / "labels.json").read_text())
    rows = []
    passed = 0
    with httpx.Client(base_url=BASE, timeout=120) as client:
        for label in labels:
            pdf = next(CLAIMS_DIR.glob(f"{label['claim_id']}_*.pdf"))
            with pdf.open("rb") as fh:
                resp = client.post("/claims", files={"file": (pdf.name, fh, "application/pdf")})
            resp.raise_for_status()
            run = resp.json()

            if run["status"] == "awaiting_review":
                # Accept the recommendation, so the final decision is what the workflow chose.
                done = client.post(
                    f"/claims/{run['run_id']}/decision",
                    json={"decision": run["recommended_decision"], "note": "batch run"},
                )
                done.raise_for_status()
                run = done.json()

            route_ok = run["route"] == label["expected_path"]
            decision_ok = run["final_decision"] == label["expected_decision"]
            ok = route_ok and decision_ok
            passed += ok
            rows.append({
                "claim_id": label["claim_id"],
                "scenario": label["scenario"],
                "expected_route": label["expected_path"],
                "actual_route": run["route"],
                "expected_decision": label["expected_decision"],
                "actual_decision": run["final_decision"],
                "match": "PASS" if ok else "FAIL",
            })

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    for r in rows:
        print(f"{r['claim_id']}  {r['scenario']:<17} {r['actual_route']:<16} {r['actual_decision']:<18} {r['match']}")
    print(f"\n{passed} of {len(rows)} claims match the expected route and decision.")
    print(f"Saved to {RESULTS}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
