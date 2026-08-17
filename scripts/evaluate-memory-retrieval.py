#!/usr/bin/env python3
import asyncio
import json
import sys
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API_DIR))

from app.evals.memory_retrieval import run_evaluation  # noqa: E402


if __name__ == "__main__":
    result = asyncio.run(run_evaluation())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)
