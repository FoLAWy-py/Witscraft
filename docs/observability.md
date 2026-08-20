# Production Observability and Incident Response

**Status:** Host-level production baseline

Witscraft evaluates a versioned, metadata-only service-level policy every five minutes. The
baseline is deliberately usable on the current single-host deployment and does not require a
third-party telemetry account. It detects local service, database, model, queue, and backup
failures; an external paging destination and distributed tracing remain separate future work.

## Signals and privacy boundary

The API writes a dedicated rotating access-metrics log when
`OPERATIONAL_METRICS_LOG_PATH` is configured. Production startup rejects a missing or relative
path. Each record contains only the UTC observation time, validated request ID, HTTP method,
matched route template, status code, and elapsed milliseconds. An unmatched request is recorded
as `unmatched`. Raw paths, query strings, client addresses, account/story identifiers, cookies,
headers, request bodies, prompts, and responses are never written to this log.

The evaluator combines those records with `/health/ready`, metadata-only `ModelCall` audit rows,
generation coordination rows, durable embedding-task state, and encrypted backup sidecars. Model
aggregates include provider/model/purpose, counts, token totals, estimated cost, latency, time to
first token, fallback attempts, and success rate. Only explicit non-dry-run OpenAI and DeepInfra
calls are included; test-labelled models and deterministic local calls are excluded.

Files are created under a mode-`700` runtime directory. Metrics, state, and reports are mode
`600`; the access log rotates at 5 MB with five retained files by default. All runtime outputs must
remain under ignored operator-controlled storage and must not be committed.

## Versioned SLO policy

`production-slo-v1` evaluates a rolling 30-minute window:

| Signal | Alert threshold |
| --- | ---: |
| Public readiness | Any failed observation |
| Metrics database access | Any failed observation |
| HTTP 5xx rate | More than 1% after 20 eligible requests |
| Non-stream HTTP p95 | More than 2.5 seconds after 20 samples |
| External model success | Less than 95% after 5 calls |
| External model p95 | More than 60 seconds after 5 samples |
| External model TTFT p95 | More than 15 seconds after 5 samples |
| Processing generation age | More than 10 minutes |
| Eligible embedding queue age | More than 15 minutes |
| Stale embedding lease or dead letter | Any row |
| Newest complete encrypted backup | Missing or older than 26 hours |

Health, administrator, and browser preflight requests do not affect the HTTP availability SLI.
Stream duration is excluded from ordinary request latency because it includes intentional reading
time. Low traffic is reported as `insufficient_samples`; it does not fabricate a pass rate or page
an operator. Readiness, database, queue, and backup checks have no sample minimum.

## Operation

Install `ops/launchd/com.witscraft.slo-monitor.plist.example` after replacing its placeholders in
an ignored deployment file. The production API and monitor must read the same secrets file, and
the API's `OPERATIONAL_METRICS_LOG_PATH` must match the monitor's `--api-log` argument.

Run one observation manually with runtime-specific paths:

```bash
apps/api/.venv/bin/python scripts/check-production-slos.py \
  https://deployment.example/witscraft \
  --api-log /absolute/runtime/access-metrics.log \
  --backup-dir /absolute/runtime/backups \
  --state-file /absolute/runtime/slo-alert-state.json \
  --report-file /absolute/runtime/slo-report.json
```

Exit `0` means no active alert, exit `2` means the observation contains an SLO alert, and exit `3`
means the monitor itself could not run safely. The state file retains first/last seen timestamps
and consecutive observations for active alerts, and records resolutions on the next successful
observation. Standard output is suitable for supervisor logs but contains no credentials or user
content.

## Incident runbook

1. Confirm whether the alert persists across two observations, except readiness/database failure,
   a stuck generation, a stale lease, or a missing backup, which require immediate triage.
2. Correlate application logs and model audit metadata with the request ID; do not add request
   bodies or prompts to telemetry.
3. For `readiness_failed` or `metrics_database_failed`, stop releases, check PostgreSQL reachability
   and migration head, then run the non-mutating release smoke check. Never run a destructive
   restore or downgrade without explicit approval.
4. For model success/latency/TTFT alerts, inspect the provider/purpose aggregates and circuit
   breaker. Preserve player state, avoid repeated live probes, and switch routes only through the
   audited administrator flow after the approved provider evidence supports it.
5. For generation or embedding alerts, inspect coordination status and leases. Reclaim only via
   the documented worker mechanism; never edit story rows or task leases by hand.
6. For `backup_missing_or_old`, stop data-changing releases, run the backup command, verify all
   artifact sidecars, and follow `docs/backup-recovery.md`. Do not claim recovery readiness from an
   unverified file.
7. For an unexpected token/cost increase, disable optional live validation, inspect aggregate
   purpose/model usage and quota policy, and preserve audit rows. Never print provider keys or
   prompts while investigating.
8. Record the affected window, alert code, request IDs, mitigation, recovery evidence, and follow-up
   action in the operator incident record. User-content samples require a separate privacy review.

The host-level state is not an external pager. Until an approved telemetry destination exists, the
operator must review the supervisor log and private alert state during releases and routine host
checks. Adding a remote sink changes the data-transfer boundary and requires privacy and security
review first.
