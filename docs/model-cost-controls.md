# Model cost controls

Witscraft applies cost controls before provider traffic leaves the API. The LLM Gateway is the enforcement boundary for both streamed and non-streamed requests, including primary generation, fallback models, and auxiliary model calls.

## Purpose budgets

| Purpose | Maximum input | Default output | Maximum output |
| --- | ---: | ---: | ---: |
| Critical story generation | 16,000 | 4,800 | 8,192 |
| Normal chat | 10,000 | 2,400 | 4,096 |
| State update | 8,000 | 1,000 | 1,800 |
| Event extraction | 6,000 | 800 | 1,400 |
| Summary generation | 12,000 | 1,200 | 1,800 |
| Consistency check | 12,000 | 1,200 | 2,400 |

Input values use the application's conservative estimator. A request above its purpose input limit is rejected before quota preflight or provider execution. The API returns HTTP `413` for an oversized chat request, and streaming returns an SSE error with the same status.

The effective output maximum is the lower of the purpose limit and the selected model's registered capability. A caller may request less than the default or explicitly request an expanded result up to that effective maximum. Fallback models inherit the already-normalized purpose limit.

The provider catalogue exposes `purpose_budgets` so clients can explain the backend policy without recreating it. The backend remains the source of truth.

## Model roles

Purpose routes are grouped into independent operational roles: AI author, structured extraction, continuity revision, and context summary. Their registered defaults currently happen to use the same approved model, but each role has a separate configuration constant and can evolve only through its own quality and cost evidence. This prevents a narrative-model decision from silently changing durable state extraction or conditional revision behavior.

Memory embedding is a fifth, deployment-controlled role. It is not stored in user purpose routes because its model, dimensions, and version define vector compatibility for persisted memories. `GET /api/providers` exposes only its provider, model, dimensions, and version; credentials and provider infrastructure remain server-side. Changing the model or version requires controlled re-embedding; changing the fixed 1,024-dimensional contract also requires a database migration rather than an interactive route save.

## Purpose route resolution

The API resolves a validated saved user route for each purpose and falls back to the model registry's system default when no valid user route exists. This same resolution path covers the AI-authored narrative response and auxiliary state extraction, event extraction, choice generation, consistency checks, planning interviews, story drafts, and summaries. Persisted routes with an unknown purpose, unknown model, or provider/model mismatch are excluded from effective routing.

Clients submit the purpose, not an independently assembled provider/model pair. The provider catalogue returns `effective_routes` with the provider, model, source, and effective budgets for every purpose, and context preview reports the route that would author the next narrative turn. Optional legacy hints are accepted only when both fields are present and match that route; otherwise the API returns HTTP `409` before story mutation or provider execution. Provider health tests remain an explicit operator-selected model probe and do not change saved routes.

Route changes are serialized per account and store complete before/after snapshots atomically with the active route rows. Saving the current effective configuration is a no-op and does not create a misleading audit event. The authenticated history endpoint is bounded to 100 entries per request. Undo restores the latest event's prior snapshot and records a linked `revert` event, preserving both cost-policy provenance and the ability to reverse an accidental rollback.

## Consistency revision gate

Canon, scene-state, character, and world-rule checks execute locally and add no model call. Their result separates high-severity errors from warnings. A warning is retained as local evidence and cannot trigger the `consistency_check` route. In automatic mode, only at least one local error permits a single revision request. The revised narrative is checked again locally and replaces the original only when its error count is zero; an empty revision, provider failure, or surviving error keeps the original response. Manual mode never invokes the revision route automatically.

## Embedding reuse

`TurnContext` owns query embedding reuse for one request/turn. The context is reset whenever a new audited turn begins, so cached narrative inputs cannot cross requests, stories, users, or turns.

The first unique query records a normal embedding call. Reuse records a second audit row with:

- `cache_hit=true`;
- zero input and output tokens;
- zero estimated cost;
- the embedding dimensions; and
- `request.avoided_input_tokens`, which estimates the provider work avoided by the cache.

Cache-hit rows therefore measure optimization value without consuming the weekly token allowance or inflating provider cost reconciliation.

## Long-term memory admission

Extracted memory is filtered before embedding or persistence. A deterministic importance score rewards consequential event language and references to known characters or inventory entities from the current state. Short, generic actions that do not reach the acceptance threshold are discarded.

Accepted candidates are compared with recent active memories after punctuation and whitespace normalization. High textual similarity is treated as a duplicate unless both memories have known, disjoint entity sets; this prevents a repeated paraphrase from incurring another embedding while preserving similar events that happened to different characters. Exact duplicate checks remain branch-scoped across the complete active set.

When extraction repeats an existing event, the stored content and embedding remain unchanged while importance, entity tags, and recency are refreshed. Manual importance-only edits likewise reuse the existing vector. A manual content change clears stale entity tags and vector metadata, updates the normalized content hash, and upserts a durable embedding task in the same database commit. An exact active duplicate returns HTTP `409` without an embedding call. Newly accepted extracted memories are persisted with their task, allowing the player response to complete without waiting for the embedding provider.

The computed importance and matched entity tags are stored with accepted memories and used by retrieval ranking and inspection. These rules are local and deterministic: they do not add another model call, and rejected candidates never reach the embedding provider.

Every completed embedding is bound to a normalized SHA-256 content hash, provider-qualified model identifier, vector dimensions, operator-controlled `EMBEDDING_VERSION`, and UTC generation time. A worker lease and expected hash prevent an old attempt from overwriting newer memory content. Failures use bounded exponential retry; exhausted tasks enter a queryable dead-letter state with sanitized errors. Migration `0014` labels existing vectors `legacy:unversioned` / `legacy-v0`; migration `0017` adds authoritative `vector(1024)` storage and moves only dimension-compatible JSONB values; migration `0018` adds the durable task ledger. Controlled re-indexing queues only active, incompatible rows and does not run during normal retrieval.

Memory retrieval always applies deterministic keyword, entity, importance, and relative-recency scoring. Semantic similarity is an additional signal only when the active set exceeds `MEMORY_VECTOR_SEARCH_MIN_ITEMS`, which defaults to 40, and at least one candidate matches the current model and embedding version. Exact cosine scoring for current fixed vectors runs in PostgreSQL inside the authorized story/branch candidate set; legacy JSONB vectors retain a compatibility calculation only when their metadata matches. If every stored vector is legacy or incompatible, retrieval skips the query embedding entirely instead of paying for a vector that cannot be compared.

## Weekly allowance interaction

Quota preflight uses estimated input plus the normalized maximum output. Purpose limits therefore bound both the possible provider charge and the amount reserved by preflight. Successful external usage is later reconciled from recorded provider tokens. Local deterministic embeddings, dry-run responses, failed calls, and cache-hit rows do not consume the weekly allowance.

Standard accounts receive an explicit soft warning at `USER_WEEKLY_TOKEN_SOFT_LIMIT_PERCENTAGE`, which defaults to 80%. The quota API returns both the threshold and whether it has been reached; the workspace changes the usage meter state and asks the user to monitor the remaining allowance. The soft threshold does not silently change model routing. At the hard weekly limit, provider preflight returns HTTP `429` with the current usage and reset boundary.

Every story and story-independent auxiliary call consumes the same account-wide weekly allowance. No per-story ceiling or story-scoped quota query exists. The preflight sums successful, non-local, non-dry-run audit rows for the account and returns `scope=account` on rejection. Administrators are exempt. Ordinary players see only the percentage used; administrators retain token totals for governance.

## Per-turn call ceiling

`LLM_MAX_EXTERNAL_CALLS_PER_TURN` defaults to 8 and applies to every real provider request in one audited turn. Each LLM retry, fallback attempt, auxiliary call, and external embedding request reserves one slot immediately before network execution. Local deterministic embeddings, cache hits, and dry-run model operations do not reserve slots.

The auditor resets the counter when it begins a new turn. Exhaustion stops the chain before another provider request and returns an explicit HTTP or SSE `429` response. This ceiling bounds pathological retry or orchestration behavior independently of token estimates and the weekly allowance.

Story creation makes one logical `normal_chat` request to plan the requested 3–120 chapter roadmap. Output is capped at the smaller of 8,192 tokens or the planner's count-scaled budget, and the request remains subject to the shared weekly quota, route budget, retry/fallback policy, and external-call ceiling. Quota exhaustion is reported instead of silently downgrading. Other provider failures or invalid structured output use a deterministic local roadmap so story creation remains available, and `roadmap_source` preserves whether the accepted plan was provider-generated or fallback-generated. The planner does not create embeddings.

Narrative output allowance scales with the configured chapter target: the conservative request uses 1.15 tokens per requested CJK character or 1.6 tokens per requested whitespace-delimited word, plus a small structural reserve, and never exceeds the selected purpose/model hard ceiling. This is an allowance rather than a claim that the provider will exactly meet the target; real-provider chapter-length scoring remains a release evaluation requirement. Explicit machine-readable impossible actions are rejected locally before quota preflight, and Continue changes the authoring constraint without adding an auxiliary call.

After an accepted new chapter, roadmap adaptation may make one additional `normal_chat` request for at most the next four chapters and the provisional ending. Its output allowance is 900–1,280 tokens for the normal four-chapter window and never exceeds 2,400. It does not resend the full transcript or full 120-chapter plan, does not generate embeddings, and does not run for regenerate/rewrite or after the final chapter. Invalid output, provider failure, or unavailable auxiliary quota preserves the current roadmap and the accepted narrative; no retry loop exists outside the Gateway's global bounded policy.

## Summary generation

Session summaries are user-triggered and are not generated on every narrative turn. The summarizer sends the previous cumulative branch summary together with only messages after its coverage boundary, then persists a complete replacement summary. A request with no newly uncovered message returns HTTP `409` before quota preflight or provider execution, preventing repeated charges for the same range.

Each summary stores the prompt version, actual provider and model after fallback resolution, generation trigger, parent summary, covered message range, cumulative message count, and conservative source-token estimate. Branch duplication remaps both message boundaries and parent-summary lineage to the new branch.

## Dynamic context budgets

Narrative context uses a 5,460-token shared section ceiling beneath a conservative 9,000-token input target, leaving a fixed rendering reserve for system rules, labels, and formatting. The current player message is measured first and reduces the available section pool when large. A deterministic two-stage allocator gives each demanded section a protected minimum, then redistributes remaining capacity in continuity-first rounds up to explicit maxima.

World, character, state, canon, preferences, story instructions, cumulative summary, memories, and recent messages are all trimmed against their actual allocation. Context preview returns the conservative estimator version, provider-calibration status, full demand, allocation, selected estimate, authoritative source, dropped item counts, and `dynamic_section_budget` when content was truncated. The final rendered prompt estimate remains independently visible and the LLM Gateway still enforces the purpose hard limit.

These controls are intentionally deterministic. Model or prompt changes should modify the central budget table only after regression evidence demonstrates a quality need.

## Structured model approval

The `state_update` route cannot be changed on the strength of a cheaper advertised price or a single valid JSON response. Its approval record is checked against the registry in CI and release preflight. A new default requires a bounded provider capture over the exact versioned corpus, with at least 99% parse success, 95% scalar accuracy, 90% collection F1, 95% relationship F1, 100% critical-invariant success, and at most 2% accepted hallucinations. Cost and latency remain additional selection inputs after the quality floor passes.

The checked-in synthetic reference consumes no provider quota and cannot approve a new model. Captures should be reused while prompt, case hash, provider model version, and adapter semantics remain unchanged. This prevents repeated evaluation spend and avoids treating CI mocks as supplier-quality evidence.
