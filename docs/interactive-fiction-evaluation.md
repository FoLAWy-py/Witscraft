# Interactive Fiction Provider Evaluation

**Status:** Required release gate

**Evaluation version:** `interactive-fiction-natural-pacing-v2`

**Last updated:** 24 August 2026

## Purpose

This gate measures the player-facing AI author with real supplier behavior. Offline fixtures test parsing and policy enforcement, but they never become model-quality scores. A release is approved only by a reviewed `provider_capture` whose identities and deterministic measurements match the versioned case.

## Corpus and rights

Version 1 uses a reviewed excerpt from Chapter I of Jane Austen's *Pride and Prejudice*, obtained from [Project Gutenberg eBook 1342](https://www.gutenberg.org/ebooks/1342). The text is public domain in the United States and is used only to derive abstract features such as sentence-length variation, paragraph rhythm, dialogue ratio, viewpoint, tense, density, and pacing. The capture never sends the reference text to the judge, stores it in a story, or asks for author imitation.

The canonical files are under `apps/api/evals/interactive_fiction/v1/`:

- `reference.txt` is the normalized public-domain input;
- `case.json` binds its hash, scenario, prompt versions, expected abstract profile, and provider routes;
- `thresholds.json` defines the release minimums;
- `provider-capture-v6-style-v3-approved.json` is the current sanitized real-provider evidence;
- `provider-capture-v4-approved.json` preserves the previous target-length contract evidence;
- `provider-capture-v4.json` preserves the first v4 run, which passed agency but missed style and roadmap/length thresholds;
- `provider-capture-v3.json` preserves the preceding approved v3 evidence;
- `provider-capture.json` preserves the preceding approved v2 evidence; and
- `failed-provider-capture-overlength.json` preserves the preceding failed run that exposed the deterministic length-ceiling defect.

## Capture boundary

The capture utility creates a temporary verified account, imports the reference twice, and proves that the second import reuses the compatible local profile with zero provider or embedding calls. It then traverses authenticated story creation and one player-action chapter through the production API. Model-call audit rows must show DeepInfra `Qwen/Qwen3-Max` authoring and OpenAI `gpt-5.5` agency enforcement. A separate OpenAI `gpt-5.5` request judges only the abstract profile, scenario contract, and generated prose.

Live capture is sequential, requires both configured provider credentials, refuses dry-run mode, requires explicit `--confirm-live-provider`, and stops at eight total calls. Its `finally` path deletes the temporary account and verifies cleanup. The output excludes credentials, raw reference text, cookies, account identifiers, prompt bodies, and infrastructure addresses.

## Approved evidence

The current installment-aware capture passed every version 2 threshold. It proves that a completed provider installment can return control below the chapter minimum without closing the chapter, while the agency editor still binds first-person player instructions to the named protagonist. The minimum applies only to an actual chapter transition; it is not a per-turn target:

| Measurement | Result |
| --- | ---: |
| Abstract-profile adherence | 76 |
| Narrative quality | 88 |
| Player agency | 91 |
| World and canon | 86 |
| Narrative pacing | 89 |
| Overall | 86 |
| Prose length | 443-word installment / 500 chapter minimum |
| Provider completion | completed |
| Chapter transition | remained active |
| Reference overlap | 0 blocked overlap |
| Provider calls | 5 total / 8 maximum |
| Profiling calls | 0 |

The score source is `provider_capture`. These figures describe one regression case and are release evidence, not a broad literary benchmark.

## Commands

Offline replay is safe for CI and consumes no provider quota:

```bash
cd apps/api
uv run python ../../scripts/evaluate-interactive-fiction.py
```

An authorized recapture is intentionally separate:

```bash
cd apps/api
uv run python ../../scripts/capture-interactive-fiction.py \
  --base-url <approved-api-url> \
  --deployment-revision <40-character-git-revision> \
  --output <new-immutable-json-path> \
  --confirm-live-provider
```

Never overwrite reviewed evidence. Capture to a new path, inspect the generated prose, audit routes, measurements, cleanup result, and secrets scan, then deliberately replace the canonical evidence in a reviewed commit.

## Invalidation policy

A new live capture is required when any bound provider/model route, corpus hash, authoring or judge prompt version, style-analysis version, non-reproduction rule, agency editor, or chapter post-processing contract changes. Documentation-only, frontend-only, and unrelated deterministic backend changes reuse the capture. CI always replays existing evidence and never receives supplier credentials.
