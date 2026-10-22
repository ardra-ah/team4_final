"""Start the claim API. Use this instead of calling uvicorn directly.

On networks that inspect HTTPS traffic (company firewalls), Python does not trust the
inspection certificate, so LangSmith and other HTTPS calls fail. truststore makes Python
use the Windows certificate store, which already trusts that certificate.

Run from the project folder:
    pip install truststore
    python scripts\\run_api.py
"""

import sys
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import uvicorn  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
