# Administrator Access and Weekly AI Quotas

**Status:** Production baseline
**Last updated:** 17 August 2026

## Purpose

Witscraft applies a weekly AI token allowance to standard users and provides a separate administrator console for account-level usage governance. The design limits privileged access to the minimum information required for cost control.

## Roles and Permission Boundary

| Capability | Standard user | Administrator |
| --- | --- | --- |
| Play and customize interactive novels | Yes | Yes |
| View personal weekly usage, percentage, and reset time | Yes | Yes |
| View account names, emails, roles, and weekly token totals | No | Yes |
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

`USER_WEEKLY_TOKEN_QUOTA` defines the standard-user account allowance and defaults to `500000` tokens. `STORY_WEEKLY_TOKEN_QUOTA` independently limits each interactive novel to `250000` tokens in the same window, preventing one narrative from consuming the complete account allowance. Story creation and provider health checks have no story scope and therefore use only the account boundary. Administrators are exempt from both limits so that operational diagnosis and recovery are not blocked by user budgets.

`USER_WEEKLY_TOKEN_SOFT_LIMIT_PERCENTAGE` defines a visible warning threshold and defaults to `80`. Reaching it changes the user's quota meter to a warning state without blocking requests or silently changing the selected model. The hard allowance continues to reject provider preflight with HTTP `429` and the reset boundary.

The natural quota window starts each Monday at `00:00 UTC` and ends the following Monday at `00:00 UTC`. The user interface displays the boundary in the viewer's local time zone. Successful external LLM and embedding calls contribute their input and output token usage from the `model_calls` audit table. Local deterministic embeddings and dry-run model responses do not consume the allowance.

Before an external request begins, the LLM Gateway checks the estimated input plus the configured maximum output against the remaining account allowance and, when a story is active, that story's allowance. A rejected request returns HTTP `429`, includes `Retry-After`, identifies `account` or `story` scope, and does not contact the model provider. Account usage remains visible in the workspace; the settings view securely loads the active novel's usage after ownership validation. Story-limit failures are explicit request errors rather than a silent route or quality change.

The current deployment uses one API process. The preflight check prevents ordinary overspend, but two requests admitted concurrently can complete slightly above the allowance because tokens are reconciled after provider completion. A durable reservation ledger is required before strict accounting across multiple workers or highly concurrent clients.

## Manual Global Reset

`POST /api/admin/quota/reset-all` creates an append-only `quota_reset_events` record. It does not delete model-call audit rows. The latest reset event within the current calendar week becomes the effective start of the quota window for every user.

The administrator console requires a second confirmation before reset. The endpoint is independently role protected and limited to five attempts per administrator session in 15 minutes by default. `RATE_LIMIT_ADMIN_RESET_REQUESTS` can change this operational limit.

Manual reset is global by design. Per-user exceptions are not currently supported because they complicate policy explanation and auditability. A future per-user adjustment should use an append-only grant or reset ledger rather than editing usage history.

## API Surface

| Endpoint | Access | Purpose |
| --- | --- | --- |
| `GET /api/quota/me` | Authenticated user | Personal usage, percentage, period, and remaining tokens |
| `GET /api/admin/overview` | Administrator | Aggregated account usage for the current quota window |
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

1. Restart the API process if an environment value changed.
2. Verify `/health/ready` returns HTTP `200` and migration revision `0013`.
3. Sign in with a standard account and verify the usage percentage and local reset time.
4. Verify a standard account receives HTTP `403` from `/api/admin/overview`.
5. Sign in with an authorized administrator and verify the console before using reset.
