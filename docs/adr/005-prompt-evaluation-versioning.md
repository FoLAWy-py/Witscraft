# ADR-005: Prompt and evaluation versioning

**Status:** Accepted

**Date:** 17 August 2026

## Context

Witscraft routes AI-authored narrative and auxiliary structured tasks independently. Provider behavior, prompt changes, and post-processing changes can alter durable story state even when transport-level tests remain green. Unversioned examples or subjective spot checks cannot support a safe model-route decision.

## Decision

Every quality-sensitive model route must be governed by a named prompt version, a versioned fixed evaluation corpus, explicit metrics and thresholds, and an approval record bound to the exact corpus hash and provider/model identity.

CI uses synthetic recorded responses only to verify deterministic contracts and evaluator behavior. Synthetic evidence is never sufficient to approve a new provider route. A route change requires a complete, bounded provider capture over synthetic or properly anonymized cases, a timezone-qualified capture record, and passing quality thresholds. The capture is reused until the prompt, corpus, provider model version, or relevant adapter semantics change.

The application registry and route approval record must change atomically in one reviewed commit. A pinned legacy exception may keep a pre-evaluation default in service, but cannot be transferred to another model. Quality evidence is evaluated alongside measured token cost and latency; no single example or single metric decides rollout.

## Consequences

- Default route changes fail CI when the approval record does not match.
- Prompt changes invalidate stale response bundles by version and case hash.
- Evaluation fixtures contain no production user content or credentials.
- Provider captures consume a small, explicit, bounded amount of API quota and are never generated during normal CI.
- Additional evaluation domains may reuse this pattern while defining domain-specific rubrics and thresholds.
