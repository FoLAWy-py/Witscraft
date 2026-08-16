# Security checks

The `Security` GitHub Actions workflow runs for pull requests and pushes to `main`.
It is a release gate: do not deploy a revision while any job is failing.

## Checks

- TruffleHog scans the complete committed Git history for secret candidates. Verification is disabled so suspected credentials are never sent to a provider API.
- `pip-audit` checks the installed Python dependency graph created from `uv.lock`.
- `npm audit` checks production and development packages from `package-lock.json` and fails at high severity.
- Production API tests ensure schema documentation is disabled and unhandled exceptions do not expose tracebacks or exception messages.
- The production frontend build is rejected if public static assets contain sourcemaps, source-map directives, private-key headers, or server-only secret variable names.

All third-party GitHub Actions are pinned to immutable commit SHAs. Tool versions are explicit so a scanner update cannot silently change a previously reproducible result.

## Local commands

Run the dependency checks with network access:

```bash
cd apps/api
uv sync --frozen --all-extras
uv run --with pip-audit==2.10.1 pip-audit --local
```

```bash
cd apps/web
npm ci
npm audit --audit-level=high
npm run build:production
cd ../..
python3 scripts/check-production-artifacts.py
```

TruffleHog is intentionally run in CI against committed history. If a credential is detected, revoke and rotate it before removing it from current files; deleting a line does not remove the credential from Git history.
