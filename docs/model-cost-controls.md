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

## Purpose route resolution

The API resolves a validated saved user route for each purpose and falls back to the model registry's system default when no valid user route exists. This same resolution path covers the AI-authored narrative response and auxiliary state extraction, event extraction, choice generation, consistency checks, planning interviews, story drafts, and summaries. Persisted routes with an unknown purpose, unknown model, or provider/model mismatch are excluded from effective routing.

Clients submit the purpose, not an independently assembled provider/model pair. The provider catalogue returns `effective_routes` with the provider, model, source, and effective budgets for every purpose, and context preview reports the route that would author the next narrative turn. Optional legacy hints are accepted only when both fields are present and match that route; otherwise the API returns HTTP `409` before story mutation or provider execution. Provider health tests remain an explicit operator-selected model probe and do not change saved routes.

Route changes are serialized per account and store complete before/after snapshots atomically with the active route rows. Saving the current effective configuration is a no-op and does not create a misleading audit event. The authenticated history endpoint is bounded to 100 entries per request. Undo restores the latest event's prior snapshot and records a linked `revert` event, preserving both cost-policy provenance and the ability to reverse an accidental rollback.

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

When extraction repeats an existing event, the stored content and embedding remain unchanged while importance, entity tags, and recency are refreshed. Manual importance-only edits likewise reuse the existing vector. A manual content change clears stale entity tags and replaces the embedding plus all compatibility metadata in the same database commit; an exact active duplicate returns HTTP `409` before embedding. Provider failure therefore cannot commit new content alongside an old vector.

The computed importance and matched entity tags are stored with accepted memories and used by retrieval ranking and inspection. These rules are local and deterministic: they do not add another model call, and rejected candidates never reach the embedding provider.

Every accepted or manually refreshed embedding is bound to a normalized SHA-256 content hash, provider-qualified model identifier, vector dimensions, operator-controlled `EMBEDDING_VERSION`, and UTC generation time. Semantic ranking compares a query only with memories whose model, dimensions, and version all match. Migration `0014` labels existing vectors `legacy:unversioned` / `legacy-v0`, so they remain available to structured importance and recency ranking without being silently compared to a new vector space.

Memory retrieval always applies deterministic keyword, entity, importance, and relative-recency scoring. Semantic similarity is an additional signal only when the active set exceeds `MEMORY_VECTOR_SEARCH_MIN_ITEMS`, which defaults to 40, and at least one candidate matches the current model and embedding version. If every stored vector is legacy or incompatible, retrieval skips the query embedding entirely instead of paying for a vector that cannot be compared.

## Weekly allowance interaction

Quota preflight uses estimated input plus the normalized maximum output. Purpose limits therefore bound both the possible provider charge and the amount reserved by preflight. Successful external usage is later reconciled from recorded provider tokens. Local deterministic embeddings, dry-run responses, failed calls, and cache-hit rows do not consume the weekly allowance.

Standard accounts receive an explicit soft warning at `USER_WEEKLY_TOKEN_SOFT_LIMIT_PERCENTAGE`, which defaults to 80%. The quota API returns both the threshold and whether it has been reached; the workspace changes the usage meter state and asks the user to monitor the remaining allowance. The soft threshold does not silently change model routing. At the hard weekly limit, provider preflight returns HTTP `429` with the current usage and reset boundary.

The same preflight applies `STORY_WEEKLY_TOKEN_QUOTA`, 250,000 tokens by default, whenever the audited turn belongs to an existing interactive novel. Account and story usage use the same successful, non-local, non-dry-run audit rows and reset window. The account limit is checked first; a story rejection then reports `scope=story`. The quota endpoint accepts an owned story identifier and returns its consumed, limit, remaining, and percentage values for the settings view; unknown or cross-tenant identifiers return `404`. New-story planning and provider health checks have no story identifier and remain governed by the account limit only. Administrators are exempt from both boundaries.

## Per-turn call ceiling

`LLM_MAX_EXTERNAL_CALLS_PER_TURN` defaults to 8 and applies to every real provider request in one audited turn. Each LLM retry, fallback attempt, auxiliary call, and external embedding request reserves one slot immediately before network execution. Local deterministic embeddings, cache hits, and dry-run model operations do not reserve slots.

The auditor resets the counter when it begins a new turn. Exhaustion stops the chain before another provider request and returns an explicit HTTP or SSE `429` response. This ceiling bounds pathological retry or orchestration behavior independently of token estimates and the weekly allowance.

## Summary generation

Session summaries are user-triggered and are not generated on every narrative turn. The summarizer sends the previous cumulative branch summary together with only messages after its coverage boundary, then persists a complete replacement summary. A request with no newly uncovered message returns HTTP `409` before quota preflight or provider execution, preventing repeated charges for the same range.

Each summary stores the prompt version, actual provider and model after fallback resolution, generation trigger, parent summary, covered message range, cumulative message count, and conservative source-token estimate. Branch duplication remaps both message boundaries and parent-summary lineage to the new branch.

## Dynamic context budgets

Narrative context uses a 5,460-token shared section ceiling beneath a conservative 9,000-token input target, leaving a fixed rendering reserve for system rules, labels, and formatting. The current player message is measured first and reduces the available section pool when large. A deterministic two-stage allocator gives each demanded section a protected minimum, then redistributes remaining capacity in continuity-first rounds up to explicit maxima.

World, character, state, canon, preferences, story instructions, cumulative summary, memories, and recent messages are all trimmed against their actual allocation. Context preview returns the conservative estimator version, provider-calibration status, full demand, allocation, selected estimate, authoritative source, dropped item counts, and `dynamic_section_budget` when content was truncated. The final rendered prompt estimate remains independently visible and the LLM Gateway still enforces the purpose hard limit.

These controls are intentionally deterministic. Model or prompt changes should modify the central budget table only after regression evidence demonstrates a quality need.
