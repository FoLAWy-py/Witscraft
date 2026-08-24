# LAN Staging Release Candidate

**Status:** Operational, isolated, and non-public

Witscraft staging reproduces the single-host production boundary without changing the public deployment. A TLS Nginx gateway is reachable on the local network; the Next.js production build, FastAPI API, and embedding worker run as supervised launchd jobs. PostgreSQL remains bound to loopback and is never exposed directly to the LAN.

## Runtime topology

| Boundary | Runtime | Network exposure |
| --- | --- | --- |
| Player gateway | Nginx TLS | LAN host on port `19473` |
| Web application | Next.js production server | loopback port `18321` |
| API and SSE | Uvicorn/FastAPI | loopback port `18322` |
| Database | PostgreSQL 18.6 + pgvector 0.8.6 | loopback port `15432` |
| Background work | memory embedding worker | no listener |

The gateway listens on all local IPv4 and IPv6 interfaces. On first preparation it
records the primary LAN address plus any other detected RFC 1918 addresses (for
example a private VPN address), and includes all of them in the TLS certificate,
Host allowlist, CORS origins, and CSRF origins. PostgreSQL, the API, and the web
process remain loopback-only; LAN clients must use the TLS gateway. Override the
aliases before first preparation with the comma-separated
`WITSCRAFT_STAGING_ADDITIONAL_HOSTS` setting when automatic detection is unsuitable.

### Trusting the LAN certificate on a client

The gateway uses a 30-day, staging-only self-signed certificate. A new client can
reach the server immediately, but its browser will reject the certificate until
the public certificate is trusted. Transfer only
`.runtime/staging/tls/server.crt` to the client through a trusted LAN channel;
never copy `server.key`. Before trusting it, compare the SHA-256 fingerprint shown
on the server:

```bash
openssl x509 -in .runtime/staging/tls/server.crt -noout -fingerprint -sha256
```

On macOS, import the certificate into the login keychain with Keychain Access and
set it to **Always Trust** only for this staging environment. On Windows, import it
for the current user into **Trusted Root Certification Authorities**. Remove the
old certificate when staging is retired or the certificate rotates. Client URLs
are `https://<LAN-address>:19473/witscraft/`; both the ordinary LAN address and
detected private-VPN aliases are valid certificate identities.

The database uses a PostgreSQL 18 parent-directory volume mount at `/var/lib/postgresql`, allowing major-version-specific cluster directories and future `pg_upgrade` workflows. The previous PG17 staging volume is not attached or deleted by the upgrade.

## Operator workflow

All private state is generated beneath ignored `.runtime/staging` with directory mode `0700` and secret, certificate, state, and evidence files mode `0600`.

```bash
scripts/staging-release.sh prepare
scripts/staging-release.sh start
scripts/staging-release.sh status
scripts/staging-release.sh smoke \
  --manifest /absolute/path/to/.runtime/staging/candidate.json
scripts/staging-release.sh verify-resilience
scripts/staging-release.sh observe --minutes 30
scripts/staging-release.sh stop
```

The LAN URL and self-signed staging certificate are runtime values. Share the certificate only with authorized test devices and trust it only for this isolated endpoint. Never copy it into a production trust store or commit it.

`start` is idempotent: it validates production configuration, starts the pinned PostgreSQL image, applies Alembic migrations explicitly, rejects migration drift, creates a production frontend build, supervises all processes, validates Nginx configuration, and waits for HTTPS readiness. A failed start cleans up application processes without deleting database volumes.

## Verification workflows

`verify-resilience` injects and verifies these recoverable failures:

- API upstream unavailable: Nginx returns normalized HTTP `503` with `Retry-After`;
- slow upstream timeout: Nginx returns normalized HTTP `503` rather than an opaque 502/504 page;
- API process crash: launchd restarts the process and readiness recovers;
- PostgreSQL outage: readiness returns `503`, then recovers after the pinned container is healthy;
- post-recovery smoke: liveness, readiness, and Alembic revision match the candidate manifest.

`live-experience --confirm-live-provider` is intentionally separate. It disables worker embedding traffic, limits the journey to 12 provider calls, creates a temporary verified account, proves local style-profile reuse without provider work, executes player-action/Continue/player-action turns, judges the ordered experience with a real provider, checks account-wide quota percentage and natural chapter pacing, deletes the account, and restores normal retry/fallback settings.

The encrypted backup workflow uses `scripts/backup-postgres.sh`. Recovery must target a new `witscraft_restore_*` database through `scripts/restore-postgres.sh --drop-after-verify`; it must never overwrite staging in place.

## Security boundary

- Do not bind PostgreSQL, Uvicorn, or Next.js to the LAN.
- Do not add public DNS, router forwarding, tunnelling, or public certificates to this environment.
- Do not commit `.runtime`, provider output, private certificates, IP addresses, credentials, or database artifacts.
- Use only synthetic accounts and stories. Real user content and restored production data are prohibited.
- Stop and require operator approval before any destructive volume removal or public deployment.

## Acceptance

A release candidate is acceptable only when PostgreSQL and pgvector versions are pinned and observed, migration head and schema drift checks pass, the deterministic API journey and full backend suite pass on PostgreSQL 18, the encrypted restore drill succeeds, resilience verification passes, the bounded provider gates pass, and a 30-minute observation records zero UI or readiness failures. Participant HCI validation remains a separate human-subject gate.
