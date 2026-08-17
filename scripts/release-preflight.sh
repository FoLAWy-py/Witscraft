#!/bin/zsh
set -euo pipefail

ROOT="${WITSCRAFT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
REVISION="$(git -C "$ROOT" rev-parse --short=12 HEAD)"
MANIFEST="${1:-$ROOT/.runtime/releases/$REVISION.json}"

if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]; then
  print -u2 "Release preflight requires a clean tracked worktree"
  exit 1
fi

cd "$ROOT/apps/api"
uv sync --frozen --all-extras
uv run --with pip-audit==2.10.1 pip-audit --local
uv run ruff check app tests migrations ../../scripts/create-release-manifest.py ../../scripts/evaluate-structured-extraction.py ../../scripts/smoke-release.py
uv run python ../../scripts/evaluate-structured-extraction.py
uv run pytest -q

cd "$ROOT/apps/web"
npm ci
npm audit --audit-level=high
npm run lint
npm run typecheck
npm run build:production
npm run test:e2e

cd "$ROOT"
python3 scripts/check-production-artifacts.py
python3 scripts/create-release-manifest.py --output "$MANIFEST"
print "Release preflight passed for $REVISION"
print "Manifest: $MANIFEST"
