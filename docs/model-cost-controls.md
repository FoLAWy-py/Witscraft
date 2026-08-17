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

## Weekly allowance interaction

Quota preflight uses estimated input plus the normalized maximum output. Purpose limits therefore bound both the possible provider charge and the amount reserved by preflight. Successful external usage is later reconciled from recorded provider tokens. Local deterministic embeddings, dry-run responses, failed calls, and cache-hit rows do not consume the weekly allowance.

These controls are intentionally deterministic. Model or prompt changes should modify the central budget table only after regression evidence demonstrates a quality need.
