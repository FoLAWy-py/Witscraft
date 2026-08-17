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

The computed importance and matched entity tags are stored with accepted memories and used by retrieval ranking and inspection. These rules are local and deterministic: they do not add another model call, and rejected candidates never reach the embedding provider.

## Weekly allowance interaction

Quota preflight uses estimated input plus the normalized maximum output. Purpose limits therefore bound both the possible provider charge and the amount reserved by preflight. Successful external usage is later reconciled from recorded provider tokens. Local deterministic embeddings, dry-run responses, failed calls, and cache-hit rows do not consume the weekly allowance.

Standard accounts receive an explicit soft warning at `USER_WEEKLY_TOKEN_SOFT_LIMIT_PERCENTAGE`, which defaults to 80%. The quota API returns both the threshold and whether it has been reached; the workspace changes the usage meter state and asks the user to monitor the remaining allowance. The soft threshold does not silently change model routing. At the hard weekly limit, provider preflight returns HTTP `429` with the current usage and reset boundary.

The same preflight applies `STORY_WEEKLY_TOKEN_QUOTA`, 250,000 tokens by default, whenever the audited turn belongs to an existing interactive novel. Account and story usage use the same successful, non-local, non-dry-run audit rows and reset window. The account limit is checked first; a story rejection then reports `scope=story`. The quota endpoint accepts an owned story identifier and returns its consumed, limit, remaining, and percentage values for the settings view; unknown or cross-tenant identifiers return `404`. New-story planning and provider health checks have no story identifier and remain governed by the account limit only. Administrators are exempt from both boundaries.

## Per-turn call ceiling

`LLM_MAX_EXTERNAL_CALLS_PER_TURN` defaults to 8 and applies to every real provider request in one audited turn. Each LLM retry, fallback attempt, auxiliary call, and external embedding request reserves one slot immediately before network execution. Local deterministic embeddings, cache hits, and dry-run model operations do not reserve slots.

The auditor resets the counter when it begins a new turn. Exhaustion stops the chain before another provider request and returns an explicit HTTP or SSE `429` response. This ceiling bounds pathological retry or orchestration behavior independently of token estimates and the weekly allowance.

These controls are intentionally deterministic. Model or prompt changes should modify the central budget table only after regression evidence demonstrates a quality need.
