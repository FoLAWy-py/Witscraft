# ADR-003: Fixed pgvector embedding dimension and upgrade boundary

**Status:** Accepted

**Date:** 17 August 2026

## Context

Long-term-memory embeddings were stored in JSONB with model, dimension, version, content-hash, and generation-time metadata. JSONB preserved legacy vectors but could not provide a typed database similarity boundary or a future approximate index. The configured OpenAI `text-embedding-3-large` model returns 3,072 dimensions by default and supports an explicit `dimensions` parameter. pgvector can store vectors above 2,000 dimensions, but its HNSW and IVFFlat `vector` indexes support at most 2,000 dimensions.

## Decision

- The production embedding contract is `text-embedding-3-large`, 1,024 dimensions, version `v2-pgvector-1024`.
- Every provider request passes `dimensions=1024`; a missing, non-finite, count-mismatched, or dimension-mismatched response is rejected before persistence.
- Migration `0017` installs the `vector` extension and adds nullable `vector(1024)` storage. Dimension-compatible JSONB values are moved into that column and cleared from JSONB.
- New compatible embeddings use the vector column as their authoritative storage. JSONB remains only as an explicit compatibility lane for legacy or deterministic test vectors with other dimensions until controlled re-embedding replaces them.
- Runtime configuration must match the schema dimension. Changing the dimension requires a new migration and embedding-version change; it is not a normal environment-only edit.
- No HNSW or IVFFlat index is created yet. Exact candidate-set ranking remains in application memory until a fixed recall corpus and production-shaped row counts establish an index threshold and parameters.

## Consequences

The database now rejects silent current-vector dimension drift and has a typed path for database-side cosine ranking. Existing incompatible memories remain usable through keyword, entity, importance, and recency signals without a forced provider call. A later background re-embedding workflow must migrate legacy rows without blocking player responses. Storage and similarity quality for the 1,024-dimensional contract must be tracked through Recall@K and latency evaluation before approximate indexing is enabled.

Authoritative dependency behavior is documented by the [OpenAI embeddings guide](https://developers.openai.com/api/docs/guides/embeddings) and the [pgvector project](https://github.com/pgvector/pgvector).
