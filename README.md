# Witscraft

Witscraft is a customizable AI-authored interactive novel. The AI acts as the author and narrator, while the user plays a character and decides the direction of the plot through actions and choices. Stories support 3–120 chapter roadmaps, a language-aware minimum chapter-development guard, and optional rights-attested reference text that becomes a reusable abstract style profile without retaining or embedding the source. The minimum prevents premature chapter breaks; it is never a target or maximum. Normal turns preserve exclusive player control over the protagonist; an explicit Continue action delegates only one reversible turn. The application follows the architecture in `system architecture.md`: a Next.js frontend, a FastAPI backend, PostgreSQL with fixed-dimension pgvector memory storage, and an LLM Gateway that hides OpenAI and DeepInfra differences from story logic.

Ordinary player-action responses are buffered until a fail-closed OpenAI agency edit removes any protagonist behavior not explicitly supplied by the player. This quality boundary and bounded provider-truncation repair are audited, share the account-wide weekly allowance, and stay within the per-turn external-call ceiling; **Continue** remains the only one-turn delegation.

## Project Shape

```text
apps/
  api/    FastAPI backend, story engine, prompt builder, LLM gateway
  web/    Next.js interactive novel experience with route-private UI and domain API modules
```

## Documentation

- [`system architecture.md`](./system%20architecture.md): formal production architecture, runtime boundaries, and controlled evolution path
- [`docs/data-privacy.md`](./docs/data-privacy.md): account export, deletion, retention, and model-provider data boundaries
- [`docs/database-performance.md`](./docs/database-performance.md): repeatable PostgreSQL query-plan benchmark and index policy
- [`docs/backup-recovery.md`](./docs/backup-recovery.md): encrypted backup operation, restore procedure, RPO/RTO, and drill evidence
- [`docs/observability.md`](./docs/observability.md): metadata-only production SLOs, host alerts, and incident runbooks
- [`docs/development-story-reset.md`](./docs/development-story-reset.md): guarded, backup-required cleanup of development story data
- [`docs/memory-retrieval-evaluation.md`](./docs/memory-retrieval-evaluation.md): fixed Recall@8, error-recall, and PostgreSQL latency gate
- [`docs/background-jobs.md`](./docs/background-jobs.md): durable memory embedding worker, re-indexing, and queue monitoring
- [`docs/admin-and-quota.md`](./docs/admin-and-quota.md): administrator permission boundary, weekly AI allowance, and reset operation
- [`docs/model-cost-controls.md`](./docs/model-cost-controls.md): purpose-level model budgets, embedding cache metrics, and quota interaction
- [`docs/structured-extraction-evaluation.md`](./docs/structured-extraction-evaluation.md): versioned state-extraction corpus, metrics, evidence classes, and model-approval gate
- [`docs/interactive-fiction-contract.md`](./docs/interactive-fiction-contract.md): player-agency, chapter, roadmap, revision, reference-text, and provider-evaluation acceptance rules
- [`docs/interactive-fiction-evaluation.md`](./docs/interactive-fiction-evaluation.md): versioned public-domain corpus, bounded live capture, provider scores, and offline release gate
- [`docs/hci-evaluation.md`](./docs/hci-evaluation.md): independent HCI rubric, expert walkthrough, issue severity, and participant-validation gate
- [`docs/security-checks.md`](./docs/security-checks.md): dependency, secret, and production artifact security gates
- [`docs/release-process.md`](./docs/release-process.md): executable preflight, release manifest, smoke checks, and rollback contract

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
Migration `0012` adds concurrently-built indexes for branch timelines, active memory/canon retrieval, workspace ownership filters, model-call inspection, and critical foreign-key maintenance. Migration `0013` adds administrator roles, global quota reset events, and the per-user model-call index used by weekly usage accounting. Migration `0014` adds model, dimension, version, content-hash, and timestamp metadata to memory embeddings and backfills existing rows as explicitly incompatible legacy vectors. Migration `0015` adds branch-local cumulative-summary lineage, prompt version, actual provider/model provenance, and generation trigger metadata. Migration `0016` adds immutable before/after snapshots for purpose-route changes and indexed per-user history. Migration `0017` enables pgvector, adds fixed `vector(1024)` storage, migrates compatible JSONB embeddings, and preserves incompatible values for controlled re-embedding. Migration `0018` adds durable, leased memory-embedding tasks with bounded retries and dead-letter state. Migration `0019` adds the append-only, administrator-authored account quota policy ledger. Migration `0020` adds constrained chapter counts and the original length-planning field, branch-local roadmaps and endings, chapter/message integrity, and abstract style profiles that never store reference prose. Migration `0021` adds explicit provider/fallback/legacy provenance for each branch roadmap. Migration `0022` gives the 500–5,000 character/word field minimum-only semantics, associates every message with its branch-local chapter, and enforces that association with a scoped foreign key. Story creation accepts 3–120 chapters, persists a complete validated roadmap, and hides future titles and the provisional ending behind a spoiler control. The AI closes a chapter only after the minimum and a natural narrative break with objective resolution, or at an explicitly exceptional terminal break; no target, maximum, padding, or forced trimming exists. While a story is active, the player may atomically extend or shorten every branch plan from the roadmap panel; accepted/current chapters are protected, stale roadmap versions are rejected, and the adjustment itself consumes no model allowance. A player may also correct a branch-local canon fact through an explicit before/after confirmation: the prior fact remains as superseded history, accepted prose is unchanged, and only future chapter plans plus the provisional ending are conservatively invalidated. Compatible semantic scores use exact PostgreSQL cosine distance inside the authorized story/branch candidate set; HNSW remains disabled pending production-shaped Recall@K and latency evidence. The rollback-only 230,000-row `EXPLAIN ANALYZE` benchmark is documented in `docs/database-performance.md`.

Operational probes have separate meanings: `/health/live` checks only process responsiveness, while `/health/ready` verifies required non-billable configuration, PostgreSQL connectivity, and the deployed Alembic revision. A release is not ready until the database revision matches the application migration head.

Production also writes a private rotating access-metrics stream containing only request IDs, route templates, status codes, and durations. A five-minute host monitor combines it with readiness, real-provider audit aggregates, generation/embedding coordination state, and encrypted-backup freshness under the versioned `production-slo-v1` policy. It never exports user content; external paging and distributed tracing remain future operator-approved integrations.

The production host runs `scripts/backup-postgres.sh` daily through a LaunchAgent. Backups use PostgreSQL custom format, Zstandard compression, and CMS AES-256-GCM public-key encryption. Recovery operation and the latest drill evidence are documented in `docs/backup-recovery.md`; off-site replication remains disabled until its external destination is explicitly approved.

## Production Security Boundary

Production startup fails unless database credentials, at least one model provider, SMTP, HTTPS cookies, an HTTPS frontend URL, exact CORS origins, an explicit Host allowlist, and an absolute operational-metrics path are configured. Wildcard hosts, wildcard CORS, private-LAN CORS regexes and dry-run models are rejected.

Unsafe browser requests validate `Origin` against the frontend/CORS allowlist. Cross-site requests carrying the session cookie are rejected even when `Origin` is absent but `Sec-Fetch-Site: cross-site` is present. CLI/API requests without browser cross-site metadata remain supported. Uvicorn trusts forwarded headers only from the local Nginx address.

Production also applies separate sliding-window limits to registration, login, verification/password-reset email, provider tests, story generation and export. A rejected request returns `429` with `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` and `X-Request-ID`. Limits are process-local for the current single API process; use a shared Redis-backed limiter before enabling multiple API workers.

Application and Uvicorn logs redact authentication headers, cookies, passwords, API/SMTP secrets, sensitive URL parameters and explicitly logged prompt/message fields. Model audit rows store counts and metadata instead of prompt or response text, and provider errors are sanitized before persistence. Keep request IDs for correlation rather than adding request bodies to logs.

Production disables FastAPI's interactive documentation and OpenAPI schema endpoints, never enables debug exception responses, and does not publish browser sourcemaps. The repository security workflow scans committed history, locked dependency graphs and production browser artifacts on every pull request and push to `main`.

## Model Routing

The current backend default for every story purpose is `Qwen/Qwen3-Max`. The registry also exposes alternative DeepInfra and OpenAI models, and an authenticated user can save purpose-specific routes. The backend is the only routing authority: every AI-authored narrative call and auxiliary state, event, consistency, interview, draft, or summary call resolves the user's saved route first and otherwise uses the registered system default.

Defaults are declared through separate operational roles even while their approved model values currently coincide: AI author, structured extraction, continuity revision, context summary, and memory embedding. `GET /api/providers` exposes this role manifest so the settings view can explain which tasks author prose, which tasks only maintain continuity, and which embedding configuration is deployment-controlled. Embedding is not a player-selectable narrative route; changing its model, 1,024-dimensional schema contract, or version requires a migration and controlled re-embedding.

The browser submits the story purpose rather than assembling a provider/model pair. `GET /api/providers` exposes an `effective_routes` manifest, and context preview reports the effective route for the selected narrative purpose. During client migration, an optional legacy provider/model pair is accepted only when it matches the current backend route; a stale pair is rejected with HTTP `409` before narrative state is written. Provider credentials and infrastructure base URLs remain server-side.

Route updates are serialized per account and append an immutable before/after snapshot in the same database transaction as the active routes. The settings view can undo the latest change; that undo is itself audited and can be undone again. No-op saves create no audit noise. Route history is included in account export and removed with the account.

The `state_update` default is pinned to a versioned route-approval record. Its model-quality score is calculated from the reviewed eight-case `state-extraction-v3` DeepInfra responses, including nullable chapter-decision normalization; the synthetic contract tests the evaluator only. The default CI command directly replays the immutable provider capture without new network spend and reports `score_source=provider_capture`; it does not substitute a synthetic score. The current route passes every parse, accuracy, F1, critical-invariant, and hallucination threshold. A replacement default still requires its own complete provider capture bound to the exact case hash and prompt version; see [`docs/structured-extraction-evaluation.md`](./docs/structured-extraction-evaluation.md).

The AI-authoring release gate follows the same evidence rule. Its reviewed end-to-end capture uses DeepInfra `Qwen/Qwen3-Max` to author the chapter and OpenAI `gpt-5.5` to enforce agency and independently judge quality. CI replays the sanitized capture without provider credentials and verifies its corpus, prompt versions, route audit, length, non-reproduction measurements, and real-provider scores. See [`docs/interactive-fiction-evaluation.md`](./docs/interactive-fiction-evaluation.md).

## Model Call Auditing

Migration `0009` records LLM and embedding calls with a shared request/turn ID, status, token usage, latency and optional versioned cost estimate. Prompt and response text are not stored in the audit row.

Query embedding reuse is scoped to one turn. A cache hit records zero billable tokens and zero estimated cost while preserving the estimated avoided input tokens for operational analysis. Purpose-specific input and output limits are enforced centrally by the LLM Gateway; see [`docs/model-cost-controls.md`](./docs/model-cost-controls.md).

Long-term-memory candidates are scored and checked for normalized near-duplicates before embedding. Low-value transient actions are discarded, while a repeated event refreshes the existing memory's ranking metadata without replacing its content or vector. Accepted memories retain computed importance and current character/inventory entity tags for retrieval ranking. Retrieval combines keyword overlap, entity tags, importance, relative update time, and compatible-vector similarity. Semantic query embeddings activate only when the candidate set exceeds `MEMORY_VECTOR_SEARCH_MIN_ITEMS` and contains a current model/version vector, so small or legacy-only sets remain deterministic and cost-free. Manual importance-only edits reuse the existing embedding. Content changes atomically clear stale vector metadata and enqueue the replacement before returning; exact active duplicates are rejected without provider work. Accepted extracted memories follow the same queue, so an embedding provider cannot add latency to the player-facing narrative transaction.

Session summaries are currently created only by an explicit player action, never automatically on every turn. Each new summary is a cumulative replacement that incorporates the prior branch summary plus only newly uncovered messages. It records its parent, complete covered range, prompt version, actual provider/model, trigger, source-token estimate, and cumulative message count. Repeating the action without new messages returns HTTP `409` before a model call.

Narrative consistency rules run locally on every enabled turn and report explicit error and warning counts. Warnings remain local and never spend model tokens. In automatic mode, only a locally detected `error` can trigger the purpose-routed revision model, and revised prose replaces the AI author's original response only after a second local check confirms that every high-severity error is gone. Manual mode reports the same evidence without an automatic model call.

Story context uses one deterministic 5,460-token section pool under a conservative 9,000-token input target. Minimum allocations protect current state and continuity signals, while unused capacity is redistributed up to per-section maxima. A long player message automatically reduces the section pool. The context-preview endpoint reports estimator identity, demand, allocation, selected tokens, source, dropped counts, and a truncation reason for every section; the state snapshot itself is trimmed rather than merely reporting an unenforced budget.

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
LLM_MAX_EXTERNAL_CALLS_PER_TURN=8
LLM_CIRCUIT_FAILURE_THRESHOLD=3
LLM_CIRCUIT_COOLDOWN_SECONDS=30
STREAM_CHECKPOINT_SECONDS=1
STREAM_CHECKPOINT_CHARACTERS=512
GENERATION_STALE_SECONDS=900
AUTH_LOGIN_THROTTLE_RETENTION_HOURS=24
MODEL_CALL_RETENTION_DAYS=30
EMBEDDING_VERSION=v1
MEMORY_VECTOR_SEARCH_MIN_ITEMS=40
MEMORY_EMBEDDING_TASK_MAX_ATTEMPTS=5
MEMORY_EMBEDDING_WORKER_BATCH_SIZE=25
MEMORY_EMBEDDING_WORKER_POLL_SECONDS=5
MEMORY_EMBEDDING_WORKER_LEASE_SECONDS=300
USER_WEEKLY_TOKEN_QUOTA=500000
USER_WEEKLY_TOKEN_SOFT_LIMIT_PERCENTAGE=80
RATE_LIMIT_ADMIN_RESET_REQUESTS=5
```

The circuit breaker is process-local. This is sufficient for the current single API process; move health state to shared infrastructure before running multiple API workers if coordinated failover is required.

## Administrator and Weekly Quota

Standard users receive one weekly account allowance shared by every interactive novel and auxiliary provider call. The deployment default is 500,000 tokens and the persisted administrator policy can replace it without a process restart. The ordinary-player workspace exposes only the usage percentage; raw token accounting remains available to administrators. The administrator console shows the deterministic 4-token-to-3-word planning estimate, serializes policy updates, retains append-only change history, and can begin a new global quota window without deleting model-call audit history. Administrators are exempt from the allowance.

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
  -d '{"message":"我压低声音问林岚：这把钥匙到底能打开什么？","purpose":"normal_chat","max_output_tokens":512}'
```
