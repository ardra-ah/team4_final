"""Start the claim API, reading settings from the .env file in the project folder.

Use this instead of uvicorn or run_api.py. Put your settings in .env, for example:
    DATABASE_URL=...
    GEMINI_API_KEY=...
    LLM_ENABLED=1
    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=...
    LANGSMITH_PROJECT=claim-review

Run from the project folder:
    python scripts\\start_api.py

Values already set in the terminal take priority over .env.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

# Use the Windows certificate store so company HTTPS inspection does not break LangSmith/Gemini.
import truststore  # noqa: E402

truststore.inject_into_ssl()

import uvicorn  # noqa: E402

sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
