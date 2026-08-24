# Structured extraction evaluation

**Status:** Versioned production gate for the `state_update` route

## Purpose

Witscraft uses a structured model call to convert an AI-authored narrative turn into durable scene state, inventory, unresolved threads, relationships, memories, and canon facts. A cheaper or faster model must not become the default merely because it returns valid JSON in one demonstration. This gate measures recorded responses against a fixed, synthetic, anonymized corpus before a route change can be approved.

The current corpus is `structured-extraction-v1` and is bound to prompt version `state-extraction-v3`, the exact system-prompt SHA-256, and the canonical case-set SHA-256. It covers quiet turns, explicit arrival, planned destinations, abstract perspective language, inventory removal and addition, resolved threads, explicit kinship, title/alias canonicalization, and conservative chapter-decision normalization.

## Evidence classes

The repository contains `reference_responses.json` with `evidence_kind=synthetic_contract`. It validates the application merge logic, grounding rules, evaluator, metrics, and thresholds deterministically in CI. It is not evidence of any provider model's quality and cannot approve a new route.

A model-selection bundle must use `evidence_kind=provider_capture` and include:

- the exact evaluation and prompt versions;
- the canonical SHA-256 hash of the case set;
- provider and model identifiers;
- a timezone-qualified capture timestamp;
- `capture_method=bounded_live_provider`;
- exactly one recorded raw response for every case.

The approval validator rejects synthetic evidence, partial coverage, stale case hashes, prompt-version mismatches, path traversal, and captures whose provider/model identity differs from the proposed route. Captures must contain only the supplied synthetic cases and provider responses; never include credentials, request headers, account data, or production narrative content.

## Metrics and thresholds

| Metric | Approval threshold | Meaning |
| --- | ---: | --- |
| JSON/schema parse success | at least 99% | Response reaches the validated structured merge path |
| Scalar accuracy | at least 95% | Location, time, mood, and objective match expected end state |
| Collection F1 | at least 90% | Inventory, open threads, memories, and canon facts |
| Relationship F1 | at least 95% | Canonical relationship tuple accuracy |
| Critical assertion pass rate | 100% | Safety-sensitive invariants such as no planned-location jump |
| Accepted hallucination rate | at most 2% | Unexpected persisted atomic values among predictions |

The thresholds are versioned in `apps/api/evals/structured_extraction/v1/thresholds.json`. Weakening a threshold is an evaluation-policy change and requires review; it must not be used to make a failing candidate pass.

## Commands

Re-score the current route from its immutable real-provider capture, without new provider traffic:

```bash
cd apps/api
uv run python ../../scripts/evaluate-structured-extraction.py
```

Run the synthetic evaluator contract explicitly when changing evaluator behavior:

```bash
cd apps/api
uv run python ../../scripts/evaluate-structured-extraction.py \
  --responses evals/structured_extraction/v1/reference_responses.json
```

Evaluate a previously captured candidate bundle:

```bash
cd apps/api
uv run python ../../scripts/evaluate-structured-extraction.py \
  --responses /approved/path/provider-capture.json \
  --require-provider-evidence \
  --output /tmp/structured-extraction-report.json
```

The evaluator never contacts a provider. A live capture is a separate, explicitly authorized and bounded operation. The repository capture command refuses dry-run mode, requires an explicit billable-call acknowledgement, accepts only registered provider/model pairs, performs no more than eight sequential calls, writes no credentials or provider request metadata, and refuses to overwrite immutable evidence:

```bash
cd apps/api
uv run python ../../scripts/capture-structured-extraction.py \
  --provider deepinfra \
  --model Qwen/Qwen3-Max \
  --output evals/structured_extraction/v1/provider-capture.json \
  --confirm-live-provider
```

Do not generate a new capture on every CI run or conversation. Reuse it while the case hash, prompt version, provider model version, and relevant adapter behavior remain unchanged.

## Route approval lifecycle

`route_approval.json` is checked against the registered `state_update` default on every CI run and release preflight. The current DeepInfra `Qwen/Qwen3-Max` route is approved by the reviewed `state-extraction-v3` provider capture. Model quality scores are calculated from those real provider responses. CI replays the immutable capture without new provider traffic and reports `score_source=provider_capture` plus the provider-evidence metrics; synthetic reference metrics test only the evaluator and can never be presented as the model's score. The gate fails if the prompt, corpus, route identity, thresholds, or deterministic post-processing changes incompatibly.

## Current provider evidence

The first bounded capture against `state-extraction-v1` used 3,782 input and 803 output tokens over eight calls. JSON parsing and critical assertions passed, but scalar accuracy was 90.6%, collection F1 was 73.4%, relationship F1 was 75%, and accepted hallucination rate was 27.6%; it was retained as failed evidence and never approved.

The failure drove `state-extraction-v2` and stricter deterministic acceptance rules: mood and objectives require source grounding, planned actions cannot become open threads, unresolved threads survive unless explicitly resolved, relationship kinship overrides use source-exact labels, and memories/canon facts use bounded source-span and event-category rules. Version 3 adds the chapter pacing decision to the same call, safely treats provider nulls as continue, and never permits deterministic fallback to close a chapter. The alias case also stopped expecting a relationship label that the supplied text could not support.

The second bounded capture used 4,598 input and 670 output tokens over eight calls with 20,059 ms aggregate provider latency. Replaying the unchanged provider responses through the completed deterministic boundary achieved 100% parse success, scalar accuracy, collection F1, relationship F1, and critical assertions, with 0% accepted hallucinations. This capture approves only the exact current route, prompt, corpus, thresholds, and post-processing behavior.

The current version 3 capture used 5,822 input and 1,173 output tokens over eight calls with 40,707 ms aggregate provider latency. It also achieves 100% parse success, scalar accuracy, collection F1, relationship F1, and critical assertions with 0% accepted hallucinations. The provider returned null for some new chapter-decision fields; the production parser conservatively normalized them to Continue, which is the approved fail-safe behavior.

To change the default:

1. Obtain explicit authorization for a bounded provider capture.
2. Capture every synthetic case once with the proposed provider/model and the exact prompt version.
3. Store or review the non-sensitive response bundle in the approved evidence location.
4. Run the evaluator with `--require-provider-evidence` and retain the report.
5. Update `route_approval.json` to `provider_capture`, reference the in-tree reviewed bundle, and change the registry default in the same pull request.
6. Compare quality, measured token cost, and latency before enabling broader presets or traffic.

Synthetic reference success proves the evaluation machinery. Only a passing provider capture can prove candidate model eligibility.
