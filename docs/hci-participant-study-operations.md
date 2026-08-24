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

After eligibility and observation consent are confirmed, create one private
incomplete facilitator form. All confirmation flags are required so the tool cannot
silently assume eligibility:

```bash
python3 scripts/evaluate-hci-participant-study.py session-template \
  --output .runtime/hci/sessions/P-0123ABCD.json \
  --participant-code P-0123ABCD \
  --session-date 2026-08-25 \
  --device-class desktop \
  --viewport-class desktop \
  --experience-band regular \
  --confirm-adult \
  --confirm-target-reader \
  --confirm-non-contributor \
  --confirm-task-script-unexposed \
  --confirm-observation-consent
```

After the rehearsal confirms the workflow, initialize a separate `formal` record.
Never rename rehearsal data as formal data.

Provision a verified synthetic account for a generated code. Run from the API
environment with the staging secrets file; the command refuses non-staging database
names, non-loopback backends, missing database TLS, and non-HTTPS candidates:

```bash
cd apps/api
WITSCRAFT_SECRETS_FILE=../../.runtime/staging/api.env \
  uv run python ../../scripts/manage-hci-study-account.py \
  --confirm-isolated-staging create \
  --participant-code P-0123ABCD \
  --output ../../.runtime/hci/accounts/P-0123ABCD.env
```

The command prints only the credential-file location, never its contents. Give the
synthetic credentials to the participant locally and do not copy them into the
study record.

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

Account deletion is an exact, confirmed operation keyed by the anonymous code. It
cascade-deletes the synthetic account data and removes its private credential file:

```bash
cd apps/api
WITSCRAFT_SECRETS_FILE=../../.runtime/staging/api.env \
  uv run python ../../scripts/manage-hci-study-account.py \
  --confirm-isolated-staging delete \
  --participant-code P-0123ABCD \
  --credentials ../../.runtime/hci/accounts/P-0123ABCD.env
```

An invalid session requires one enumerated exclusion reason. A valid unfavorable
session must remain valid and must not be removed from the result.

Use the standard SUS statements in this exact order, with 1 = strongly disagree
and 5 = strongly agree:

1. I think that I would like to use this system frequently.
2. I found the system unnecessarily complex.
3. I thought the system was easy to use.
4. I think that I would need the support of a technical person to use this system.
5. I found the various functions in this system were well integrated.
6. I thought there was too much inconsistency in this system.
7. I would imagine that most people would learn to use this system very quickly.
8. I found the system very cumbersome to use.
9. I felt very confident using the system.
10. I needed to learn a lot of things before I could get going with this system.

After completing and checking the private session form, atomically append it to the
formal study. The command validates both files, rejects duplicate participant codes,
updates the study through a mode-`0600` temporary file, and deletes the consumed
single-session file only after success:

```bash
python3 scripts/evaluate-hci-participant-study.py append-session \
  --study .runtime/hci/witscraft-hci-20260824-r1-formal.json \
  --session .runtime/hci/sessions/P-0123ABCD.json \
  --confirm-consume-session-file
```

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
