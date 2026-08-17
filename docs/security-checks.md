# CI and security checks

The `Security` GitHub Actions workflow runs for pull requests and pushes to `main`.
It is a release gate: do not deploy a revision while any job is failing.

## Checks

- TruffleHog scans the complete committed Git history for secret candidates. Verification is disabled so suspected credentials are never sent to a provider API.
- `pip-audit` checks the installed Python dependency graph created from `uv.lock`.
- `npm audit` checks production and development packages from `package-lock.json` and fails at high severity.
- Ruff checks the API, tests, and Alembic migration source.
- A temporary PostgreSQL 17 database is upgraded from empty state to the current Alembic head. `alembic check` then rejects ORM changes that do not have a matching migration.
- The complete backend test suite runs against that migrated PostgreSQL database, including authorization, quota, lifecycle, reliability, and security integration coverage. An authenticated API journey exercises login, story creation, regular and streamed generation, client cancellation, regeneration, branch switching, and export with a deterministic dry-run model. Deterministic fake clients verify OpenAI Responses and DeepInfra Chat Completions request mapping, usage parsing, streaming deltas, timeout configuration, disabled SDK retries, exception propagation, and Gateway retry classification. External model traffic is disabled in CI.
- ESLint and TypeScript validate the frontend before its production build.
- The production frontend build is rejected if public static assets contain sourcemaps, source-map directives, private-key headers, or server-only secret variable names.
- Playwright runs a real Chromium session through login, workspace loading, player input, SSE parsing, narrative rendering, and post-generation state synchronization. API responses are deterministic browser fixtures; PostgreSQL behavior is covered separately by the authenticated API journey.
- A clean CI checkout must generate a non-sensitive release manifest bound to the commit, Alembic head, dependency lock hashes, and frontend build ID.

All third-party GitHub Actions are pinned to immutable commit SHAs. Tool versions are explicit so a scanner update cannot silently change a previously reproducible result.

The workflow is necessary release evidence, but repository branch protection and the deployment operator must also require its successful result. GitHub Actions alone cannot prevent a privileged operator from deploying an unverified revision.

## Local commands

Run the dependency checks with network access:

```bash
cd apps/api
uv sync --frozen --all-extras
uv run --with pip-audit==2.10.1 pip-audit --local
uv run ruff check app tests migrations ../../scripts/create-release-manifest.py ../../scripts/evaluate-structured-extraction.py ../../scripts/smoke-release.py
uv run python ../../scripts/evaluate-structured-extraction.py
uv run alembic upgrade head
uv run alembic check
uv run pytest -q
```

```bash
cd apps/web
npm ci
npm audit --audit-level=high
npm run lint
npm run typecheck
npm run build:production
npx playwright install chromium
npm run test:e2e
cd ../..
python3 scripts/check-production-artifacts.py
python3 scripts/create-release-manifest.py --output .runtime/releases/$(git rev-parse --short=12 HEAD).json
```

TruffleHog is intentionally run in CI against committed history. If a credential is detected, revoke and rotate it before removing it from current files; deleting a line does not remove the credential from Git history.
