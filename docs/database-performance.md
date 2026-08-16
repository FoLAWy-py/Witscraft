# Database Query Performance

**Status:** Verified production baseline

**Last verified:** 16 August 2026

## Purpose

This document records the repeatable query-index benchmark for Witscraft. It covers the
high-frequency reads used to assemble narrative context and inspect recent model activity.
It is a regression baseline, not a production capacity claim.

## Method

Run the benchmark against a PostgreSQL database migrated to the revision under test:

```bash
cd apps/api
uv run python scripts/benchmark_query_indexes.py
```

The script inserts 230,000 synthetic rows into the real application tables inside one
transaction:

| Table | Synthetic rows |
| --- | ---: |
| `messages` | 100,000 |
| `story_state_snapshots` | 30,000 |
| `memory_items` | 30,000 |
| `canon_facts` | 30,000 |
| `story_summaries` | 10,000 |
| `model_calls` | 30,000 |

Ten branches share the sample workload. The benchmark runs PostgreSQL `EXPLAIN (ANALYZE,
BUFFERS, FORMAT JSON)` for the application query shapes, rolls back every synthetic row,
and refreshes table statistics against the retained data. No benchmark content is committed.

## Revision 0012 Results

Measurements were collected on the same local PostgreSQL instance immediately before and
after migration `0012_query_indexes`.

| Query | Before | After | Before plan | After plan |
| --- | ---: | ---: | --- | --- |
| Recent branch messages | 4.000 ms | 0.017 ms | Seq Scan + Sort | Index Scan |
| Latest story state | 1.108 ms | 0.007 ms | Seq Scan + Sort | Index Scan |
| Ranked active memories | 1.811 ms | 0.013 ms | Seq Scan + Sort | Index Scan |
| Ranked active canon facts | 1.691 ms | 0.016 ms | Seq Scan + Sort | Index Scan |
| Latest branch summary | 0.400 ms | 0.007 ms | Seq Scan + Sort | Index Scan |
| Latest successful story model call | 4.228 ms | 0.006 ms | Seq Scan + Sort | Index Scan |

Every measured query changed from a sequential scan with an explicit sort to a bounded index
scan. The measured execution-time reduction was 98.9% to 99.9% for this dataset. Absolute
latency will vary with hardware, cache state, concurrency, row width, and production data
distribution; the required regression property is the plan shape.

## Index Policy

Revision `0012` adds three index groups:

1. Composite indexes matching ownership, branch, and time ordering for workspace lists and
   narrative history.
2. Partial indexes for active memory/canon ranking and successful story-generation model calls.
3. Supporting indexes for foreign keys used during message cleanup, branch deletion, and parent
   branch reassignment.

Indexes are created and removed concurrently so an upgrade does not require a long exclusive
table lock. The migration is retryable and skips indexes that completed during an earlier attempt.
Because concurrent index creation cannot run inside a transaction, a failed release must still
inspect and remove any invalid index before retrying the migration.

Re-run this benchmark after changing a covered query, changing its ordering, or materially
changing table cardinality. Production slow-query telemetry remains necessary because this
controlled benchmark does not model concurrent writes, storage pressure, or tenant skew.
