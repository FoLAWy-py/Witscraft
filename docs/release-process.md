# Release Process

**Status:** Executable preflight and non-mutating smoke baseline

## Release Evidence

Run releases only from a clean commit that has a successful `Security` GitHub Actions workflow.
The local preflight installs the committed lock graphs, audits dependencies, runs all backend and
frontend gates, validates the structured-extraction contract and route approval, builds the production frontend, scans browser artifacts, and writes a release
manifest under the ignored `.runtime` directory by default:

```bash
scripts/release-preflight.sh
```

The JSON manifest contains only the full Git revision, UTC creation time, Alembic heads, SHA-256
hashes of `uv.lock` and `package-lock.json`, and the Next.js build ID. It deliberately excludes
hostnames, IP addresses, credentials, environment variables, user data, and deployment paths.
Archive the manifest beside the immutable application artifact in the approved deployment system.

## Deployment Sequence

The target PostgreSQL 17 installation must provide the pgvector extension before migration `0017` is applied, and the deployment role must be allowed to run `CREATE EXTENSION vector`. Verify this in staging before approving a production release. A missing extension is a deployment blocker; do not bypass the migration or fall back to schema creation from ORM metadata.

1. Confirm the commit and its remote Security workflow are successful.
2. Run `scripts/release-preflight.sh` and retain its manifest.
3. Back up the database and verify the encrypted artifact and manifest.
4. Apply `uv run alembic upgrade head` as a separate, recorded operation.
5. Deploy the application artifact built from the manifest revision.
6. Start the API, memory embedding worker, and web processes with operator-controlled configuration. The worker command and queue checks are defined in `docs/background-jobs.md`.
7. Run the non-mutating health and migration smoke check:

   ```bash
   python3 scripts/smoke-release.py \
     https://deployment.example/witscraft \
     --manifest .runtime/releases/<revision>.json
   ```

8. In staging, use a dedicated synthetic account to verify login, story loading, one dry-run
   generation, cancellation, branch switching, regeneration, and export. Never use recovered user
   content or a billable provider for this gate.
9. Observe error rate, readiness, model failures, memory embedding queue age/dead letters, database saturation, and logs for the agreed
   release window before declaring the release complete.

Smoke URLs are runtime arguments and must not be committed. HTTPS is mandatory except for an
explicit loopback check using `--allow-http-loopback`. URLs containing credentials, query strings,
or fragments are rejected.

## Rollback Contract

Before deployment, retain the previous application artifact, its release manifest, and the new
encrypted database backup. Application rollback is permitted only when the current database
revision is compatible with the previous manifest. Do not automatically downgrade Alembic on a
live database.

If a migration is backward compatible, stop new traffic, deploy the previous artifact, and require
its readiness and smoke checks to pass. If it is not backward compatible, keep production stopped,
restore the pre-release backup into an isolated database, validate it using the recovery procedure,
and perform an operator-approved cutover. Destructive production restore or database downgrade
always requires explicit approval.
