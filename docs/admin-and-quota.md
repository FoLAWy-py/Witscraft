# Administrator Access and Weekly AI Quotas

**Status:** Production baseline
**Last updated:** 17 August 2026

## Purpose

Witscraft applies a weekly AI token allowance to standard users and provides a separate administrator console for account-level usage governance. The design limits privileged access to the minimum information required for cost control.

## Roles and Permission Boundary

| Capability | Standard user | Administrator |
| --- | --- | --- |
| Play and customize interactive novels | Yes | Yes |
| View personal weekly usage percentage | Yes | Yes |
| View account names, emails, roles, and weekly token totals | No | Yes |
| Set the shared weekly account allowance | No | Yes |
| Reset the global quota window | No | Yes |
| Read another user's stories, messages, memories, or exports | No | No |
| Read passwords, sessions, provider secrets, raw prompts, or model responses | No | No |
| Grant or revoke administrator access through the browser | No | No |

The backend database is the role source of truth. The browser's `is_admin` value is presentational only; every administrative API request independently loads the authenticated user and verifies the persisted role.

Administrator assignment is intentionally an operator action rather than a public API:

```bash
cd apps/api
uv run python scripts/set_admin.py administrator@example.com
uv run python scripts/set_admin.py administrator@example.com --revoke
```

Role changes should be executed through controlled host access and recorded in the deployment change log.

## Weekly Allowance

`USER_WEEKLY_TOKEN_QUOTA` supplies the initial standard-account allowance and defaults to `500000` tokens. Every interactive novel, planning flow, provider health probe, and external embedding attributed to the account shares this single window. There is no per-story allowance. Once an administrator saves a policy, the latest persisted policy replaces the deployment fallback without requiring a process restart. Administrators remain exempt so operational diagnosis and recovery are not blocked by user budgets.

`USER_WEEKLY_TOKEN_SOFT_LIMIT_PERCENTAGE` defines a visible warning threshold and defaults to `80`. Reaching it changes the user's quota meter to a warning state without blocking requests or silently changing the selected model. The hard allowance continues to reject provider preflight with HTTP `429` and the reset boundary.

The natural quota window starts each Monday at `00:00 UTC` and ends the following Monday at `00:00 UTC`. Successful external LLM and embedding calls contribute their input and output token usage from the `model_calls` audit table. Local deterministic embeddings and dry-run model responses do not consume the allowance. Ordinary players see only the percentage used; token totals, the configured limit, remaining tokens, and the reset boundary are reserved for administrative governance.

Before an external request begins, the LLM Gateway checks the estimated input plus the configured maximum output against the remaining account allowance. A rejected request returns HTTP `429`, includes `Retry-After`, identifies account scope, and does not contact the model provider. The system never silently changes model route or quality to fit the quota.

The current deployment uses one API process. The preflight check prevents ordinary overspend, but two requests admitted concurrently can complete slightly above the allowance because tokens are reconciled after provider completion. A durable reservation ledger is required before strict accounting across multiple workers or highly concurrent clients.

## Administrator Policy Updates

`PUT /api/admin/quota/policy` accepts an integer allowance from `1000` through `100000000` tokens and a bounded audit reason. The transaction acquires a fixed PostgreSQL advisory lock, reads the current effective policy, and appends a `quota_policy_changes` row containing the previous limit, new limit, actor, reason, and effective time. The increasing database identity makes the latest committed row authoritative and prevents concurrent administrators from recording an ambiguous previous value.

The console displays the deterministic planning estimate `estimated_words = floor(tokens × 3 / 4)`, or four tokens for approximately three words. This estimate is deliberately simple and stable for policy comparison. It is not a provider billing measure or a promise of generated length; actual ratios vary by language, tokenizer, model, formatting, and prose style.

Policy changes affect new preflight decisions immediately. They do not reset the current usage window or rewrite model-call history. The latest 10 changes remain visible in the administrator console, including deleted-actor handling through `ON DELETE SET NULL`.

## Manual Global Reset

`POST /api/admin/quota/reset-all` creates an append-only `quota_reset_events` record. It does not delete model-call audit rows. The latest reset event within the current calendar week becomes the effective start of the quota window for every user.

The administrator console requires a second confirmation before reset. The endpoint is independently role protected and limited to five attempts per administrator session in 15 minutes by default. `RATE_LIMIT_ADMIN_RESET_REQUESTS` can change this operational limit.

Manual reset and the weekly policy are global by design. Per-user exceptions are not supported because they complicate policy explanation and auditability. A future per-user adjustment should use an append-only grant or reset ledger rather than editing usage history.

## API Surface

| Endpoint | Access | Purpose |
| --- | --- | --- |
| `GET /api/quota/me` | Authenticated user | Account-wide usage snapshot; the ordinary UI renders percentage only |
| `GET /api/admin/overview` | Administrator | Aggregated account usage for the current quota window |
| `PUT /api/admin/quota/policy` | Administrator | Persist a serialized, audited weekly account allowance |
| `POST /api/admin/quota/reset-all` | Administrator | Begin a new global quota window |

The administrator overview uses bounded grouped queries for global and current-page usage. It does not load narrative records or model content.

`GET /api/admin/overview` accepts bounded list controls:

| Parameter | Values | Default |
| --- | --- | --- |
| `search` | Account display name or email, up to 120 characters | Empty |
| `role` | `all`, `admin`, or `standard` | `all` |
| `page` | Positive integer | `1` |
| `page_size` | `10` to `100` | `25` |

Global account, administrator, and token totals always cover the complete tenant. Search, role, and pagination affect only the returned account list and its `filtered_users` count, preventing a filtered view from changing the meaning of governance metrics.

The overview also returns the latest 10 global reset events with their effective time, reason, and executing administrator identity. The event remains after an administrator account is deleted, but its actor is then shown as deleted because the foreign key is cleared; reset history never includes narrative or model content.

## Operational Checks

After changing the quota or an administrator role:

1. Restart the API process only when changing the deployment fallback; console policy changes are immediate.
2. Verify `/health/ready` returns HTTP `200` and migration revision `0019`.
3. Sign in with a standard account and verify that only the usage percentage is visible.
4. Verify a standard account receives HTTP `403` from `/api/admin/overview`.
5. Sign in with an authorized administrator and verify the console before using reset.
