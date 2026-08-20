# Data Privacy and Retention

This document defines the production data boundary for Witscraft. It describes application-enforced behavior separately from operator and model-provider responsibilities.

## Account export

An authenticated user can download a JSON export from `GET /api/auth/export` or the Data and account section in Settings. Export schema version 2 contains the account profile, session metadata, worlds, characters, abstract style profiles, stories, branches, chapter roadmaps, messages, generation records, plot events, state snapshots, summaries, canon facts (including inactive superseded correction history), memories, preferences, model routes and their change history, and sanitized model-call metadata. A story export presents only the branch's currently active canon facts so obsolete facts are not treated as narrative truth.

Exports never contain password hashes, session token hashes, action-token hashes, provider API keys, SMTP credentials, or raw embedding vectors. Export files are generated on demand and are not retained by the application.

## Account deletion

`DELETE /api/auth/account` requires the active session, the current password, and the exact confirmation value `DELETE`. A successful request removes the user and all owned application data in one database transaction, explicitly removes associated model-call records, revokes every session, and expires the browser cookie.

Deletion is immediate in the primary database. Login-throttle identifiers are irreversible hashes and are retained for no more than 24 hours under normal request traffic. Redacted operational logs may retain request metadata, but not request bodies, credentials, or full prompts.

Before production backups are enabled, the operator must define a maximum backup retention of 30 days or less, encryption, access control, and a process that prevents deleted accounts from being restored into the live service. Until that process exists, backups must not be represented as deletion-compliant.

## Application retention

| Data | Default limit | Enforcement |
| --- | ---: | --- |
| Authentication sessions | 30 days | Database expiry plus revocation on password reset or account deletion |
| Login-throttle hashes | 24 hours | Stale rows pruned during authentication traffic |
| Model-call metadata | 30 days | Stale rows pruned when audit records are written |
| Prompt and model response text in audit rows | Not stored | Audit schema stores counts, routing, latency, usage, cost, and sanitized errors only |
| Application and access logs | 30 days maximum | Deployment operator must configure rotation and deletion |
| On-demand export files | Not retained server-side | Response is streamed to the authenticated browser |

`AUTH_LOGIN_THROTTLE_RETENTION_HOURS` and `MODEL_CALL_RETENTION_DAYS` can shorten or extend the database defaults. Production operators must document and review any extension before deployment.

## Model-provider transfer

For generation requests, the selected OpenAI or DeepInfra-compatible provider receives the assembled prompt required for that turn. This can include the current user message, recent story messages, relevant world and character data, state, canon facts, preferences, summaries, and retrieved memories within dynamically allocated context budgets. The authenticated context-preview endpoint reports selected source categories and token estimates but does not create a provider call.

When semantic memory retrieval requires a remote embedding, OpenAI receives only the text being embedded. Small or empty memory sets bypass query embedding, and embeddings are not generated on every conversation turn.

Witscraft does not send account email addresses, password hashes, session tokens, authentication action tokens, SMTP credentials, or provider API keys as model input. Provider credentials and provider infrastructure base URLs remain server-side. The browser receives only registered model metadata and the backend-resolved purpose route needed to explain which model will author or support the interaction.

The chapter-planning schema stores chapter numbers, titles, objectives, completion links, roadmap versions, and branch ending titles. The optional style-profile schema stores provenance category, a normalized SHA-256 content hash, analysis version, language, abstract numeric or categorical features, and an internal fixed-size non-reproduction Bloom signature. It has no column for imported reference prose. Pasted or browser-read UTF-8 reference text is normalized and analyzed locally, is never submitted to a model, never enters story memory or an embedding task, and is discarded after the request. The web wizard does not place raw reference text in `localStorage` and clears its transient state after profiling. API responses and exports remove the internal safety signature. Model-call audit metadata continues to contain no prompt or response bodies.

Upstream retention, abuse monitoring, regional processing, and training controls are governed by the operator's provider account and contract. Before enabling a provider in production, the operator must verify its current retention and training settings, document the approved region and purpose, and disclose material changes to users.

## Operational review

Review this policy whenever a new provider, telemetry sink, backup system, analytics product, or user-data field is introduced. Changes that expand external transfer or retention require a security review before release.
