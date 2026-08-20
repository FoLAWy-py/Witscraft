# CI and security checks

The `Security` GitHub Actions workflow runs for pull requests and pushes to `main`.
It is a release gate: do not deploy a revision while any job is failing.

## Checks

- TruffleHog scans the complete committed Git history for secret candidates. Verification is disabled so suspected credentials are never sent to a provider API.
- `pip-audit` checks the installed Python dependency graph created from `uv.lock`.
- `npm audit` checks production and development packages from `package-lock.json` and fails at high severity.
- Ruff checks the API, tests, Alembic migration source, and production Python utilities including the memory embedding worker and provider-capture tools.
- A temporary PostgreSQL 17 database with pinned pgvector 0.8.6 support is upgraded to revision `0016`, seeded with a synthetic 1,024-dimensional JSONB vector, upgraded to head, checked for lossless vector backfill, downgraded and checked for JSONB restoration, cleaned, and upgraded to head again. `alembic check` then rejects ORM changes that do not have a matching migration.
- A test-only retrieval evaluator creates an isolated 10,000-row story/branch corpus and fails the release on Recall@8, designated error-recall, or p95 latency regression. It uses deterministic local embeddings, removes its data, and cannot run when `APP_ENVIRONMENT` is not `test`.
- The complete backend test suite runs against that migrated PostgreSQL database, including authorization, quota, lifecycle, reliability, and security integration coverage. The memory contract proves exact database cosine scoring at Recall@1 on opposing vectors, keeps the query inside the authorized story and branch, and fails if fixed pgvector rows fall back to Python cosine. An authenticated API journey exercises login, story creation, regular and streamed generation, client cancellation, regeneration, branch switching, and export with a deterministic dry-run model. Deterministic fake clients verify OpenAI Responses and DeepInfra Chat Completions request mapping, usage parsing, streaming deltas, timeout configuration, disabled SDK retries, exception propagation, and Gateway retry classification. External model traffic is disabled in CI.
- Backend maintenance scripts are included in Ruff checks. The development story-reset tool additionally has deterministic tests for recent encrypted-backup validation, tamper rejection, and private receipt permissions; destructive behavior is verified only against an isolated restored database before an approved development reset.
- PostgreSQL contract tests enforce the `0020` chapter-count and target-length bounds, one-active-chapter rule, completed-message requirement, branch-scoped chapter/message relationship, cascade lifecycle, and absence of raw-reference columns from style profiles.
- Roadmap service tests cover the 3/12/120 chapter boundaries, exact provider schema and sequence validation, unique titles, authoritative valid-provider results, and deterministic fallback. The authenticated database journey verifies atomic chapter creation, custom-opening completion, branch cloning, remapped message references, and explicit `0021` roadmap provenance.
- Player-agency tests verify distinct normal-turn and one-turn Continue constraints, canonical chapter headings, language-aware chapter measurement, the 85% acceptance floor, and conservative explicit-rule rejection. Chapter-expansion tests prove that only a short draft starts correction, reaching the floor stops after one call, a first improvement below the floor gets one final bounded attempt, an acceptable primary draft adds no provider call, and replacement failure preserves the best successful draft. The PostgreSQL journey proves rejection creates no message or generation row and does not move the active chapter; accepted regular and streamed replies atomically complete one chapter, while regeneration leaves the next active chapter unchanged.
- Ordinary player-action output is buffered and passed through a fail-closed OpenAI agency editor before persistence or SSE release. The player action is treated as an exhaustive untrusted whitelist; a measured result over 115% can receive one bounded trim pass. Adapter contracts also verify that OpenAI JSON mode inserts the required lowercase `json` instruction into an input message for both synchronous and streaming Responses API calls.
- Dynamic-roadmap contract tests accept only the exact supplied future window with unique bounded titles and objectives. Runtime validation also rejects collisions with completed or untouched chapter titles; provider failure leaves the roadmap unchanged, and only a valid revision may increment its version.
- Active chapter-count tests lock and resize complete multi-branch roadmaps atomically, reject stale versions and reductions across completed/current chapters, preserve unique ordered entries, hide unauthorized stories, and prove that the operation creates no model call. Chromium verifies the ordinary-player control and exact branch/version wire contract.
- Reference-style tests cover normalization and hash stability, deterministic abstract features, hidden internal signatures, unrelated-text acceptance, and seeded character/word overlap rejection. The authenticated PostgreSQL journey proves rights attestation, account-scoped cache reuse, zero profiling model calls and embedding tasks, story ownership binding, `422` rejection before assistant persistence, and disabled styled-stream partial checkpoints. Chromium verifies the optional paste/import controls, attestation, transient raw-text clearing, profile binding, and story-create wire ID.
- The interactive-fiction release evaluator replays a sanitized real-provider capture and validates its public-domain corpus hash, prompt and analysis versions, audited DeepInfra/OpenAI routes, eight-call ceiling, profile reuse, chapter-length band, overlap safety, and provider judge scores. CI never makes provider calls; synthetic evaluator fixtures cannot publish a quality score.
- ESLint and TypeScript validate the frontend before its production build.
- The production frontend build is rejected if public static assets contain sourcemaps, source-map directives, private-key headers, or server-only secret variable names.
- Playwright runs a real Chromium session through login, workspace loading, explicit player-action and Continue wire modes, SSE parsing, narrative rendering, post-generation state synchronization, chapter configuration, and the default-closed roadmap spoiler disclosure. API responses are deterministic browser fixtures; PostgreSQL behavior is covered separately by the authenticated API journey.
- A clean CI checkout must generate a non-sensitive release manifest bound to the commit, Alembic head, dependency lock hashes, and frontend build ID.

All third-party GitHub Actions are pinned to immutable commit SHAs. Tool versions are explicit so a scanner update cannot silently change a previously reproducible result.

The workflow is necessary release evidence, but repository branch protection and the deployment operator must also require its successful result. GitHub Actions alone cannot prevent a privileged operator from deploying an unverified revision.

## Local commands

Run the dependency checks with network access:

```bash
cd apps/api
uv sync --frozen --all-extras
uv run --with pip-audit==2.10.1 pip-audit --local
uv run ruff check app tests migrations ../../scripts/capture-interactive-fiction.py ../../scripts/capture-structured-extraction.py ../../scripts/check-pgvector-migration.py ../../scripts/create-release-manifest.py ../../scripts/evaluate-interactive-fiction.py ../../scripts/evaluate-memory-retrieval.py ../../scripts/evaluate-structured-extraction.py ../../scripts/run-memory-embedding-worker.py ../../scripts/smoke-release.py
uv run python ../../scripts/evaluate-structured-extraction.py
uv run python ../../scripts/evaluate-interactive-fiction.py
uv run alembic upgrade head
uv run alembic check
uv run pytest -q
```

The default structured-extraction result is calculated from the current route's immutable
real-provider capture. Synthetic responses are exercised separately by the backend test suite
and are not reported as the model-quality score.

The live interactive-fiction capture is a separate authorized operation. It requires an explicit `--confirm-live-provider` flag, refuses dry-run mode, and is capped at eight sequential supplier calls. Routine CI and release preflight reuse its reviewed immutable output without credentials or network traffic; see `docs/interactive-fiction-evaluation.md`.

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
