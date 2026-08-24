# HCI Participant Study Operations

This runbook turns the approved target-player protocol into reproducible,
privacy-minimized evidence. It does not recruit participants and must never be
used to generate synthetic participant results.

## Data boundary

The private study record lives only under ignored `.runtime/hci/` with mode
`0600`. It contains anonymous random participant codes, broad eligibility bands,
ISO dates without timestamps, device/viewport classes, task counts and durations,
structured comprehension results, confidence, SUS answers, predefined observation
codes, protocol deviations, and aggregated issues. The schema has no fields for
names, contact details, network addresses, story text, prompts, recordings,
transcripts, cookies, credentials, or free-text session notes. Unknown fields and
common sensitive-value patterns are rejected without echoing their contents.

Keep consent records outside the repository and study JSON. Do not record the
screen, audio, video, participant quotations, or story prose. Use only synthetic
accounts and fictional test input. Delete each test account and its stories after
the session.

## Freeze a candidate

Before recruitment, confirm that the tracked tree is clean, `main` equals
`origin/main`, the staging manifest names the same full revision, readiness passes,
PostgreSQL reports migration head `0022`, and the desktop, tablet, and 390×844
mobile viewports are available. Do not change the tested build during a round.

Initialize a rehearsal record first:

```bash
python3 scripts/evaluate-hci-participant-study.py init \
  --output .runtime/hci/witscraft-hci-20260824-r1-rehearsal.json \
  --manifest .runtime/staging/candidate.json \
  --study-id witscraft-hci-20260824-r1 \
  --mode rehearsal
```

Generate participant codes independently of identity or recruitment records:

```bash
python3 scripts/evaluate-hci-participant-study.py new-code
```

After the rehearsal confirms the workflow, initialize a separate `formal` record.
Never rename rehearsal data as formal data.

## Session procedure

For each participant:

1. Confirm adult target-player eligibility, non-contributor status, no prior task
   script exposure, voluntary observation consent, and a clean supported browser.
2. Confirm staging readiness and use a fresh synthetic account. Do not enter
   participant-owned reference text or personal information.
3. Execute tasks 1–10 in `docs/hci-participant-study.md` without teaching the UI.
4. For each task record one status: `independent_success`, `helped`, `failed`, or
   `not_attempted`; duration in seconds; recoverable/unrecoverable error counts;
   help requests; and backtracks.
5. Record the structured normal-action and Continue comprehension results, recovery
   attempt/result, confidence 1–5, and all ten SUS responses 1–5. Use `null` for an
   interrupted questionnaire; never impute a response.
6. Select only predefined observation and protocol-deviation codes. Convert a
   recurring issue into an aggregate `HCI-R<round>-<number>` record with severity,
   HCI principle, short sanitized title, status, and fixed revision.
7. Delete the synthetic account, clear the clean browser profile, and reconfirm
   readiness before the next participant.

An invalid session requires one enumerated exclusion reason. A valid unfavorable
session must remain valid and must not be removed from the result.

## Evaluation and evidence

Validate and preview the private record without writing a report:

```bash
python3 scripts/evaluate-hci-participant-study.py evaluate \
  --input .runtime/hci/witscraft-hci-20260824-r1-formal.json
```

When the round is complete, write the sanitized report and require the full gate:

```bash
python3 scripts/evaluate-hci-participant-study.py evaluate \
  --input .runtime/hci/witscraft-hci-20260824-r1-formal.json \
  --output docs/evidence/hci-participant-study-2026-08-24-r1.json \
  --require-pass
```

The evaluator calculates SUS, per-task errors, critical-task completion, first-scene
median, authority understanding, recovery, confidence, open severity, and retest
participant independence. Fewer than five valid formal sessions are `pending`.
Rehearsal data is always `rehearsal`. A complete round that misses any approved
threshold is `failed`, never silently excluded or rounded into a pass.

If a round fails, commit its sanitized issue evidence, remediate all severity 0/1
and threshold-blocking findings, and run a full new round with at least five valid
sessions, including at least three participant codes absent from prior rounds.

## Release handoff

Only a `passed` formal report may replace the pending participant status in release
documentation. Before committing, inspect the report for data minimization, run
the full release preflight and production-artifact scan, complete LAN smoke and
observation, and confirm CI. Never deploy this study build publicly.
