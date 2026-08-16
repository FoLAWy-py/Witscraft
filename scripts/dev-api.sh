#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../apps/api"
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
