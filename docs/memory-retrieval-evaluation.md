# Memory Retrieval Evaluation

## Scope

This gate measures Witscraft's hybrid long-term-memory retrieval path for AI-authored interactive fiction. It is a synthetic contract, not evidence of live-provider embedding quality or production traffic. The corpus contains no user data, live identifiers, credentials, or provider captures.

The evaluator requires both `APP_ENVIRONMENT=test` and a database name containing `test` or `ci`. It creates an isolated account, story, and branch in the temporary CI PostgreSQL database, removes them by foreign-key cascade, and disposes the connection pool even after failure. It uses the local deterministic embedding implementation and never contacts OpenAI or DeepInfra.

## Corpus and Production Shape

Version `memory-retrieval-v1` contains eight Chinese player-direction queries. Every case has:

- one relevant memory whose vector matches the query;
- one lexical/entity trap whose vector points in the opposite direction;
- unrelated filler memories to reach 10,000 active rows in one story branch.

Relevant and trap rows receive higher importance than filler rows so both enter the bounded 128-row candidate set. PostgreSQL computes exact cosine similarity for fixed `vector(1024)` rows. The application then combines semantic, keyword, entity, importance, and relative-recency signals and returns at most eight memories.

## Metrics and Release Thresholds

The CI gate executes 24 uncached retrievals and records:

| Metric | Threshold | Meaning |
| --- | ---: | --- |
| Recall@8 | at least 0.85 | Fraction of cases whose relevant memory appears in the first eight results |
| Error recall rate | at most 0.05 | Fraction of cases whose designated contradicted/unreliable trap appears in the first eight results |
| p95 retrieval latency | at most 500 ms | End-to-end application retrieval time on the 10,000-row CI fixture, including deterministic query embedding and both PostgreSQL reads |

Runner latency is a regression guard rather than a production SLO. A production HNSW decision requires separately captured tenant-shape, concurrency, cold-cache, Recall@8, error-recall, and p95 evidence. The synthetic gate must remain green, but it cannot authorize HNSW by itself.

## Execution

After Alembic reaches head on the pinned pgvector/PostgreSQL service, CI runs:

```text
uv run python ../../scripts/evaluate-memory-retrieval.py
```

The command prints a machine-readable JSON result and exits non-zero on any threshold violation. Corpus and thresholds are versioned under `apps/api/evals/memory_retrieval/v1`; changes require a review of both the evidence classification and the HNSW decision boundary.

## Current Accepted Baseline

The first accepted measurement will be recorded here after the new gate completes on `main`. Until that run is green, the retrieval evaluation batch is not complete and HNSW remains disabled.
