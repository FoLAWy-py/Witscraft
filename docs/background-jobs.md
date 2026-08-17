# Background Jobs

**Status:** Production baseline for durable memory embedding

## Runtime Contract

Memory admission and manual content edits persist a `memory_items` row and its
`memory_embedding_tasks` row in one PostgreSQL transaction. Player-facing API requests never wait
for an embedding provider. Run exactly one worker process for the current single-host deployment:

```bash
cd apps/api
uv run python ../../scripts/run-memory-embedding-worker.py
```

The worker claims a bounded batch with `FOR UPDATE SKIP LOCKED`, assigns a unique lease, and commits
the claim before provider work. Completion locks both records and writes a vector only when the
lease and normalized content hash still match. Re-enqueueing changed content invalidates an older
lease, while deleting a memory removes its task through the foreign key.

Failed attempts store only a sanitized error summary. Retry delay begins at 30 seconds and doubles
to a one-hour cap. `MEMORY_EMBEDDING_TASK_MAX_ATTEMPTS` defaults to 5; an exhausted task becomes
`dead` and requires operator review. Stopped workers are safe to restart: a `running` lease older
than `MEMORY_EMBEDDING_WORKER_LEASE_SECONDS` is reclaimable.

## Configuration

| Variable | Default | Purpose |
| --- | ---: | --- |
| `MEMORY_EMBEDDING_TASK_MAX_ATTEMPTS` | 5 | Maximum attempts for a newly queued task |
| `MEMORY_EMBEDDING_WORKER_BATCH_SIZE` | 25 | Maximum claims per polling iteration |
| `MEMORY_EMBEDDING_WORKER_POLL_SECONDS` | 5 | Delay after each polling iteration |
| `MEMORY_EMBEDDING_WORKER_LEASE_SECONDS` | 300 | Time before an abandoned running task can be reclaimed |

The worker uses the same deployment secret source, embedding model/version contract, weekly quota
checks, audit table, and fixed vector dimension as the API. CI and local tests set `DRY_RUN_LLM=true`
and therefore cannot contact or charge an external provider.

## Controlled Re-indexing

Queue and process one bounded batch of active memories whose vector or compatibility metadata is
missing or differs from the current model contract:

```bash
cd apps/api
uv run python ../../scripts/run-memory-embedding-worker.py \
  --enqueue-incompatible --once --batch-size 25
```

Repeat only during an approved re-index window until both `count` and `claimed` are zero. Each run
is bounded and auditable; do not schedule `--enqueue-incompatible` as the normal worker command.
Changing `EMBEDDING_VERSION`, model, or dimensions can make many rows eligible and must be preceded
by a provider-cost estimate. Do not generate embeddings merely because a retrieval request occurs.

## Monitoring and Recovery

Use metadata-only queries; never include memory content in operational dashboards or alerts:

```sql
SELECT status, count(*)
FROM memory_embedding_tasks
GROUP BY status
ORDER BY status;

SELECT min(available_at) AS oldest_available_at
FROM memory_embedding_tasks
WHERE status IN ('pending', 'retry');

SELECT memory_id, attempts, max_attempts, updated_at, last_error
FROM memory_embedding_tasks
WHERE status = 'dead'
ORDER BY updated_at DESC
LIMIT 50;
```

Alert when dead-letter count is non-zero, the oldest available task exceeds the agreed processing
SLO, or a running lease remains older than the configured lease interval plus two polling cycles.
Investigate provider availability, quota state, configuration drift, and worker supervision before
retrying. A reviewed dead task can be requeued through the bounded re-index command; the upsert
resets attempts and replaces its lease. Do not edit vectors or task leases manually.

The API readiness probe deliberately covers request-serving dependencies, not worker freshness.
Worker supervision and queue-age monitoring are therefore required release and runtime checks.
