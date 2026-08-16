# PostgreSQL Backup and Recovery

**Status:** Local automation and restoration drill verified; off-site replication pending approval

**Last verified:** 16 August 2026

## Service Objectives

| Objective | Current target | Current evidence |
| --- | ---: | --- |
| Recovery point objective (RPO) | 24 hours | Daily backup at 03:15 local time |
| Database recovery time objective (RTO) | 30 minutes | 1 second for the current 29 MB database |
| Full application smoke target | 30 minutes | Completed manually in under 5 minutes |

The measured times are recovery evidence for the current dataset, not a capacity guarantee. Repeat
the drill after material data growth, PostgreSQL upgrades, encryption-key rotation, or restore-tool
changes.

## Backup Design

`scripts/backup-postgres.sh` performs the following sequence:

1. Acquires a single-process lock and loads database credentials from the deployment secret file.
2. Creates a PostgreSQL custom-format dump with Zstandard level 9 compression.
3. Streams the dump into CMS AES-256-GCM encryption using a public recipient certificate.
4. Rejects unexpectedly small output and verifies that OpenSSL can parse the CMS envelope.
5. Writes a SHA-256 transport checksum and a non-sensitive JSON manifest.
6. Atomically publishes the artifact and optional replica.
7. Retains local artifacts for 7 days and configured replica artifacts for 35 days.

Backup artifacts, manifests, keys, logs, and database credentials remain under ignored runtime or
operator-controlled paths. None may be committed to source control.

AES-256-GCM authenticates the encrypted dump during decryption. The SHA-256 sidecar detects
transport corruption before a restore. The manifest records creation time, byte size, migration
revision, application revision, dump format, compression, encryption, and checksum without storing
database credentials or user content.

## Key Boundary

The scheduled backup process receives only `backup-recipient.pem`, which contains the public
certificate. Decryption requires the separate private key and its passphrase.

For the current host, recovery material is stored under `.runtime/backup-recovery` with mode `600`
for the initial drill. This protects the material from source-control disclosure but is not durable
disaster recovery: loss or compromise of the host can affect both the database and recovery key.

Before declaring off-site recovery complete, place the encrypted private key in an approved secrets
vault or offline medium and keep its passphrase in a separate vault. Never synchronize the private
key beside backup artifacts and never place the passphrase in a LaunchAgent or shell history.

## Scheduled Operation

The deployment installs `com.witscraft.backup` as a user LaunchAgent. It runs daily at 03:15 and on
agent load. The current host writes encrypted artifacts to `.runtime/backups` and logs to
`.runtime/backup.log`.

The tracked file `ops/launchd/com.witscraft.backup.plist.example` is a non-sensitive template.
Machine-specific paths belong in an ignored deployment copy.

Operational checks:

```bash
launchctl print gui/$(id -u)/com.witscraft.backup
tail -50 .runtime/backup.log
ls -lh .runtime/backups
```

An operator should alert if no successful artifact is newer than 26 hours, if a backup exits
non-zero, or if available disk space cannot hold at least three expected backups.

## Off-Site Replication

Set `WITSCRAFT_BACKUP_OFFSITE_DIR` to an approved synchronized or mounted destination to publish
only the encrypted artifact, checksum, and manifest. The private key and passphrase must use a
different custody path.

The repository includes the mechanism and a 35-day replica retention policy, but external transfer
is deliberately disabled on the current host until the owner explicitly approves the destination
and data transfer. A production-grade destination should provide versioning, retention protection,
access logging, and preferably object lock. A normal synchronized folder is not immutable because
deletions can propagate.

## Restore Procedure

Never restore over the production database as the first step. Select an unused database name that
starts with `witscraft_restore_` for drills.

```bash
export WITSCRAFT_BACKUP_PRIVATE_KEY=/secure/recovery/private.pem
export WITSCRAFT_BACKUP_KEY_PASSPHRASE_FILE=/secure/recovery/passphrase
scripts/restore-postgres.sh \
  .runtime/backups/witscraft-YYYYMMDDTHHMMSSZ.dump.cms \
  witscraft_restore_YYYYMMDD
```

The restore tool verifies the checksum, authenticates and decrypts the CMS envelope, validates the
`pg_restore` catalogue, refuses an existing target database, restores with ownership-neutral flags,
and reports the Alembic revision plus user/story/message counts. Failed restores remove their
partial database. Add `--drop-after-verify` for a database-only drill that should clean itself up.

For an application-level drill:

1. Point an isolated API process at the restored database.
2. Require `/health/ready` to report the expected migration revision.
3. Create an isolated fixture with `apps/api/scripts/prepare_restore_smoke.py`.
4. Log in over HTTP, load the fixture workspace, and perform a dry-run generation.
5. Confirm a new assistant message and branch-version increment.
6. Stop the isolated API and delete the restored database and temporary credentials.

The fixture script refuses any database whose name does not start with `witscraft_restore_`.
Restored private story context must not be sent to an external model during a drill without explicit
authorization.

## Drill Record: 16 August 2026

- Source database: PostgreSQL 18.4, 29 MB, migration `0012`.
- Encrypted artifact: 674,313 bytes, PostgreSQL custom format, Zstandard 9, CMS AES-256-GCM.
- Database restore: checksum, authenticated decryption, catalogue, schema, and core counts passed.
- Restored counts before fixtures: 2 users, 6 stories, and 71 messages.
- Database-only restore and verification completed in approximately 1 second.
- Isolated API login returned HTTP 200 and workspace retrieval returned the expected story.
- Dry-run generation returned HTTP 200, persisted 44 characters, and advanced branch version 0 to 1.
- The temporary API, restored databases, cookies, and response artifacts were removed.
- No recovered context was transmitted to an external model provider.

The unresolved production risk is off-site artifact replication and independently escrowed recovery
keys. Until both are complete, a total host-loss event is outside the stated RPO and RTO.
