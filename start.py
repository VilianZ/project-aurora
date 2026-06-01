#!/usr/bin/env python3
"""Start the Project AURORA FastAPI server."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parent


def main() -> None:
    env_path = ROOT / ".env"
    model_dir = ROOT / "models" / "buffalo_m"

    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        pass

    if not env_path.exists():
        print("Missing .env. Run: python setup.py")

    if not model_dir.exists():
        print("Missing models/buffalo_m. Run: python scripts/download_models.py")

    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))

    print(f"Starting AURORA server on http://{host}:{port}")
    print("Dashboard: Website/index.html")
    uvicorn.run("server.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
