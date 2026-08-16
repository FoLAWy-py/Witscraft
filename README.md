# Witscraft

Witscraft is an AI interactive novel workspace. The MVP follows the architecture in `system architecture.md`: a Next.js frontend, a FastAPI backend, PostgreSQL/pgvector-ready data boundaries, and an LLM Gateway that hides OpenAI and DeepInfra differences from story logic.

## Project Shape

```text
apps/
  api/    FastAPI backend, story engine, prompt builder, LLM gateway
  web/    Next.js frontend writing cockpit
```

## Documentation

- [`system architecture.md`](./system%20architecture.md): formal production architecture, runtime boundaries, and controlled evolution path
- [`docs/data-privacy.md`](./docs/data-privacy.md): account export, deletion, retention, and model-provider data boundaries
- [`docs/database-performance.md`](./docs/database-performance.md): repeatable PostgreSQL query-plan benchmark and index policy
- [`docs/backup-recovery.md`](./docs/backup-recovery.md): encrypted backup operation, restore procedure, RPO/RTO, and drill evidence
- [`docs/admin-and-quota.md`](./docs/admin-and-quota.md): administrator permission boundary, weekly AI allowance, and reset operation
- [`docs/security-checks.md`](./docs/security-checks.md): dependency, secret, and production artifact security gates

## Local Development

Backend:

```bash
cd apps/api
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0
```

Or from the project root:

```bash
bash scripts/dev-api.sh
```

Frontend:

```bash
cd apps/web
npm install
npm run dev
```

On another device in the same LAN, open `http://<your-computer-lan-ip>:3000`.
The frontend will call the backend at `http://<your-computer-lan-ip>:8000` unless
`NEXT_PUBLIC_API_BASE_URL` is set.

When Next.js origin validation needs the LAN host explicitly, start it with:

```bash
NEXT_ALLOWED_DEV_ORIGINS=<your-computer-lan-ip> npm run dev
```

The backend reads local development secrets from the root `env.md` file. Do not commit real secrets into a public repository. A production process never reads `env.md`; it must receive environment variables or a `WITSCRAFT_SECRETS_FILE` deployment secret file.
Database structure is versioned in `apps/api/migrations`; application startup does not mutate schema or seed users.
Migration `0012` adds concurrently-built indexes for branch timelines, active memory/canon retrieval, workspace ownership filters, model-call inspection, and critical foreign-key maintenance. Migration `0013` adds administrator roles, global quota reset events, and the per-user model-call index used by weekly usage accounting. The rollback-only 230,000-row `EXPLAIN ANALYZE` benchmark is documented in `docs/database-performance.md`.

Operational probes have separate meanings: `/health/live` checks only process responsiveness, while `/health/ready` verifies required non-billable configuration, PostgreSQL connectivity, and the deployed Alembic revision. A release is not ready until the database revision matches the application migration head.

The production host runs `scripts/backup-postgres.sh` daily through a LaunchAgent. Backups use PostgreSQL custom format, Zstandard compression, and CMS AES-256-GCM public-key encryption. Recovery operation and the latest drill evidence are documented in `docs/backup-recovery.md`; off-site replication remains disabled until its external destination is explicitly approved.

## Production Security Boundary

Production startup fails unless database credentials, at least one model provider, SMTP, HTTPS cookies, an HTTPS frontend URL, exact CORS origins and an explicit Host allowlist are configured. Wildcard hosts, wildcard CORS, private-LAN CORS regexes and dry-run models are rejected.

Unsafe browser requests validate `Origin` against the frontend/CORS allowlist. Cross-site requests carrying the session cookie are rejected even when `Origin` is absent but `Sec-Fetch-Site: cross-site` is present. CLI/API requests without browser cross-site metadata remain supported. Uvicorn trusts forwarded headers only from the local Nginx address.

Production also applies separate sliding-window limits to registration, login, verification/password-reset email, provider tests, story generation and export. A rejected request returns `429` with `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` and `X-Request-ID`. Limits are process-local for the current single API process; use a shared Redis-backed limiter before enabling multiple API workers.

Application and Uvicorn logs redact authentication headers, cookies, passwords, API/SMTP secrets, sensitive URL parameters and explicitly logged prompt/message fields. Model audit rows store counts and metadata instead of prompt or response text, and provider errors are sanitized before persistence. Keep request IDs for correlation rather than adding request bodies to logs.

Production disables FastAPI's interactive documentation and OpenAPI schema endpoints, never enables debug exception responses, and does not publish browser sourcemaps. The repository security workflow scans committed history, locked dependency graphs and production browser artifacts on every pull request and push to `main`.

## Model Routing

The current backend default for every story purpose is `Qwen/Qwen3-Max`. The registry also exposes alternative DeepInfra and OpenAI models, and the frontend can save purpose-specific routes.

## Model Call Auditing

Migration `0009` records LLM and embedding calls with a shared request/turn ID, status, token usage, latency and optional versioned cost estimate. Prompt and response text are not stored in the audit row.

Set `MODEL_PRICING_VERSION` and `MODEL_PRICING` in the production environment to enable cost estimates. Rates are supplied per million tokens and are intentionally not hardcoded in the repository:

```text
MODEL_PRICING_VERSION=<pricing-effective-date>
MODEL_PRICING={"provider:model":{"input_per_million":0,"output_per_million":0},"embedding-model":{"embedding_per_million":0}}
```

Keep these values synchronized with the provider billing configuration. When pricing is absent, token usage is still recorded and `cost_estimate` remains empty.

## Model Request Reliability

The LLM Gateway owns retries so every external attempt is auditable. Provider SDK retries are disabled. Only connection failures, timeouts, rate limits, HTTP 408/409 and provider 5xx responses are retried; invalid parameters, authentication failures, content rejection and user cancellation are not retried. Fallback models are selected by story purpose, and streaming can retry or switch models only before the first visible chunk.

Defaults can be overridden through deployment environment variables or local `env.md` values:

```text
LLM_CONNECT_TIMEOUT_SECONDS=10
LLM_READ_TIMEOUT_SECONDS=90
LLM_TOTAL_TIMEOUT_SECONDS=120
LLM_MAX_ATTEMPTS=2
LLM_RETRY_BASE_SECONDS=0.5
LLM_RETRY_MAX_SECONDS=4
LLM_MAX_FALLBACKS=1
LLM_CIRCUIT_FAILURE_THRESHOLD=3
LLM_CIRCUIT_COOLDOWN_SECONDS=30
STREAM_CHECKPOINT_SECONDS=1
STREAM_CHECKPOINT_CHARACTERS=512
GENERATION_STALE_SECONDS=900
AUTH_LOGIN_THROTTLE_RETENTION_HOURS=24
MODEL_CALL_RETENTION_DAYS=30
USER_WEEKLY_TOKEN_QUOTA=500000
RATE_LIMIT_ADMIN_RESET_REQUESTS=5
```

The circuit breaker is process-local. This is sufficient for the current single API process; move health state to shared infrastructure before running multiple API workers if coordinated failover is required.

## Administrator and Weekly Quota

Standard users receive a weekly AI token allowance that resets every Monday at `00:00 UTC`. The workspace and settings views show usage percentage, consumed and remaining tokens, and the reset time in the user's local time zone. Administrators have a separate `/admin` console, are exempt from the allowance, can review account-level usage, and can begin a new global quota window without deleting audit history.

Administrator roles are assigned only through the controlled backend CLI; there is no browser role-escalation endpoint:

```bash
cd apps/api
uv run python scripts/set_admin.py administrator@example.com
```

See [`docs/admin-and-quota.md`](./docs/admin-and-quota.md) for the permission boundary, accounting semantics, concurrency limitation, revocation command, and operational checks.

## Generation Idempotency

Migration `0010` adds a durable generation ledger and branch versions; `0011` aligns timestamp constraints. Chat clients should generate one idempotency key per user send action and reuse that key when replaying the same HTTP request. Send it as `Idempotency-Key` and/or `idempotency_key` in the JSON body, together with the latest `branch_version` from the workspace response.

- A completed key returns the stored `ChatResponse` without another model call.
- A processing, failed or cancelled key returns HTTP 409 for regular requests, or a 409 SSE error event for streams, and never starts another model call.
- Reusing a key with different content returns HTTP 409.
- Only one generation may be processing for a branch; stale processing leases expire after `GENERATION_STALE_SECONDS`.
- A stale branch version returns the same 409 response/event so another browser tab cannot silently overwrite newer story state.

Streaming partial content is checkpointed immediately once, then at the configured time or character threshold. Cancellation preserves the latest stable partial and records the generation as cancelled.

The generation transaction is split into explicit phases: reserve the idempotency key and persist the user message; read and release context; run the main model, state extraction and memory embeddings without a database write transaction; then atomically commit the assistant message, state snapshot, memories, canon facts, branch version and completed response. A final branch-version mismatch rolls back the entire completion write.

Authenticated API smoke tests, using a cookie jar created by a prior login:

```bash
curl -s -X POST http://<your-computer-lan-ip>:8000/api/providers/test \
  -b cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"provider":"deepinfra","model":"Qwen/Qwen3-Max","max_output_tokens":128}'
```

```bash
curl -s -X POST http://<your-computer-lan-ip>:8000/api/chat/send \
  -b cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"message":"我压低声音问林岚：这把钥匙到底能打开什么？","provider":"deepinfra","model":"Qwen/Qwen3-Max","purpose":"normal_chat","max_output_tokens":512}'
```
