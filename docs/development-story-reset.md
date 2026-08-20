# Development Story Data Reset

**Status:** Controlled development operation

**Last verified:** 21 August 2026

This operation deletes every story and its branch-scoped narrative data while retaining identity, authentication, reusable worlds and characters, non-story memories, user preferences, model routes, quota policy, and model-call audit history. It is intended for a deliberate development reset and is not an account-deletion or production-retention mechanism.

Deleting a `stories` row uses database foreign-key actions to remove its branches, chapter roadmaps, messages, generation requests, plot events, state snapshots, summaries, canon facts, story memories, and pending story-memory embedding tasks. Reusable abstract style profiles remain account-owned. A retained `model_calls.story_id` reference becomes `NULL`; the audit row and its usage accounting remain intact.

## Safety Contract

The cleanup tool is dry-run by default and refuses execution unless all of the following are true:

1. A backup manifest names an existing CMS AES-256-GCM artifact and matching SHA-256 sidecar.
2. The artifact size and hash match the manifest.
3. The backup is no more than 24 hours old unless the operator supplies a stricter or explicitly expanded bound no greater than seven days.
4. The backup and target database have the same Alembic revision.
5. The exact confirmation phrase is supplied.
6. A production-configured runtime receives the additional `--allow-production-runtime` acknowledgement.
7. Story counts remain unchanged between inventory and the transaction lock.

The transaction takes a fixed advisory lock and an exclusive lock on `stories`, deletes through the database lifecycle contract, verifies that every story-scoped count is zero, and verifies that all protected table counts are unchanged before commit. Any failed invariant rolls the transaction back.

After commit, the tool writes a mode-`600` JSON receipt under `.runtime/maintenance`. The receipt includes counts, schema/application revision, and backup identity. It contains no user identifier, story title, story content, provider credential, server address, or database credential. `.runtime` is excluded from Git.

## Procedure

Create and verify a fresh encrypted backup first:

```bash
scripts/backup-postgres.sh
```

Use `scripts/restore-postgres.sh` to restore that artifact into a new `witscraft_restore_*` database and verify the revision and core counts. A recovery drill should delete only that isolated database after verification.

Inventory the target without changing it:

```bash
cd apps/api
WITSCRAFT_SECRETS_FILE=/absolute/path/to/.runtime/api.env \
  uv run python scripts/clear_development_stories.py \
  --backup-manifest /absolute/path/to/backup.dump.cms.json
```

Execution additionally requires `--execute`, the exact confirmation printed by `--help`, and—when applicable—`--allow-production-runtime`. The operator must compare the dry-run scope with the approved deletion scope before adding those flags.

After execution, verify that `stories` and every story-scoped table are empty, retained table counts match the receipt, and the API can still reach the migrated database. Do not delete the backup or receipt as part of the reset.

## 21 August 2026 Evidence

A fresh revision-`0019` encrypted backup passed SHA-256, CMS envelope, and isolated restore checks. The isolated database reproduced 4 users, 6 stories, and 71 messages. The cleanup removed 6 stories, 6 branches, 71 messages, 40 state snapshots, 3 summaries, 83 canon facts, and 51 story memories. It retained 4 users, 6 worlds, 6 characters, and 429 model-call audit rows. The isolated test database was removed after verification, then the same guarded operation completed against the approved development dataset.
