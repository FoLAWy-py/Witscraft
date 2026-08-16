#!/bin/zsh
set -euo pipefail

umask 077

usage() {
  print -u2 "Usage: $0 <backup.dump.cms> <new_database_name> [--drop-after-verify]"
  exit 2
}

[[ $# -ge 2 && $# -le 3 ]] || usage

ARTIFACT="$1"
TARGET_DATABASE="$2"
DROP_AFTER_VERIFY=0
if [[ $# -eq 3 ]]; then
  [[ "$3" == "--drop-after-verify" ]] || usage
  DROP_AFTER_VERIFY=1
fi
[[ "$TARGET_DATABASE" == [A-Za-z_][A-Za-z0-9_]* ]] || {
  print -u2 "Target database name must contain only letters, numbers, and underscores"
  exit 2
}

ROOT="${WITSCRAFT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SECRETS_FILE="${WITSCRAFT_SECRETS_FILE:-$ROOT/.runtime/api.env}"
RECIPIENT_CERT="${WITSCRAFT_BACKUP_CERT:-$ROOT/.runtime/backup-recipient.pem}"
PRIVATE_KEY="${WITSCRAFT_BACKUP_PRIVATE_KEY:-}"
PASSPHRASE_FILE="${WITSCRAFT_BACKUP_KEY_PASSPHRASE_FILE:-}"
KEYCHAIN_SERVICE="${WITSCRAFT_BACKUP_KEYCHAIN_SERVICE:-}"
CHECKSUM_FILE="$ARTIFACT.sha256"

for command in createdb dropdb pg_restore psql openssl shasum; do
  command -v "$command" >/dev/null || {
    print -u2 "Required command is unavailable: $command"
    exit 1
  }
done
[[ -r "$ARTIFACT" && -r "$CHECKSUM_FILE" ]] || {
  print -u2 "Backup artifact or checksum is unavailable"
  exit 1
}
[[ -r "$SECRETS_FILE" && -r "$RECIPIENT_CERT" && -r "$PRIVATE_KEY" ]] || {
  print -u2 "Database secrets, recipient certificate, and private key are required"
  exit 1
}

set -a
source "$SECRETS_FILE"
set +a
: "${DATABASE_USERNAME:?DATABASE_USERNAME is required}"
: "${DATABASE_PASSWORD:?DATABASE_PASSWORD is required}"
DATABASE_HOST="${DATABASE_HOST:-localhost}"
DATABASE_PORT="${DATABASE_PORT:-5432}"
MAINTENANCE_DATABASE="${WITSCRAFT_RESTORE_MAINTENANCE_DATABASE:-postgres}"
export PGPASSWORD="$DATABASE_PASSWORD"

temporary_dump="$(mktemp "${TMPDIR:-/tmp}/witscraft-restore.XXXXXX.dump")"
temporary_passphrase=""
database_created=0
restore_complete=0
started_at="$(date +%s)"

cleanup() {
  rm -f "$temporary_dump"
  if [[ -n "$temporary_passphrase" ]]; then
    rm -f "$temporary_passphrase"
  fi
  if [[ "$database_created" -eq 1 && ("$restore_complete" -eq 0 || "$DROP_AFTER_VERIFY" -eq 1) ]]; then
    dropdb \
      --host "$DATABASE_HOST" --port "$DATABASE_PORT" \
      --username "$DATABASE_USERNAME" --if-exists "$TARGET_DATABASE" >/dev/null
  fi
}
trap cleanup EXIT INT TERM

if [[ -z "$PASSPHRASE_FILE" && -n "$KEYCHAIN_SERVICE" ]]; then
  command -v security >/dev/null || {
    print -u2 "macOS Keychain command is unavailable"
    exit 1
  }
  temporary_passphrase="$(mktemp "${TMPDIR:-/tmp}/witscraft-key.XXXXXX")"
  security find-generic-password \
    -a "${WITSCRAFT_BACKUP_KEYCHAIN_ACCOUNT:-recovery-key}" \
    -s "$KEYCHAIN_SERVICE" -w > "$temporary_passphrase"
  PASSPHRASE_FILE="$temporary_passphrase"
fi
[[ -r "$PASSPHRASE_FILE" ]] || {
  print -u2 "A private-key passphrase file or Keychain service is required"
  exit 1
}

(
  cd "$(dirname "$ARTIFACT")"
  shasum -a 256 -c "$(basename "$CHECKSUM_FILE")"
)

openssl cms \
  -decrypt \
  -binary \
  -inform DER \
  -in "$ARTIFACT" \
  -recip "$RECIPIENT_CERT" \
  -inkey "$PRIVATE_KEY" \
  -passin "file:$PASSPHRASE_FILE" \
  -out "$temporary_dump"
pg_restore --list "$temporary_dump" >/dev/null

database_exists="$(
  psql \
    --host "$DATABASE_HOST" --port "$DATABASE_PORT" \
    --username "$DATABASE_USERNAME" --dbname "$MAINTENANCE_DATABASE" \
    --no-psqlrc --tuples-only --no-align \
    --command "SELECT 1 FROM pg_database WHERE datname = '$TARGET_DATABASE'"
)"
[[ -z "$database_exists" ]] || {
  print -u2 "Target database already exists: $TARGET_DATABASE"
  exit 1
}

createdb \
  --host "$DATABASE_HOST" --port "$DATABASE_PORT" \
  --username "$DATABASE_USERNAME" --template template0 "$TARGET_DATABASE"
database_created=1
pg_restore \
  --host "$DATABASE_HOST" --port "$DATABASE_PORT" \
  --username "$DATABASE_USERNAME" --dbname "$TARGET_DATABASE" \
  --no-owner --no-acl --exit-on-error "$temporary_dump"

verification="$(
  psql \
    --host "$DATABASE_HOST" --port "$DATABASE_PORT" \
    --username "$DATABASE_USERNAME" --dbname "$TARGET_DATABASE" \
    --no-psqlrc --tuples-only --no-align --field-separator '|' \
    --command "
      SELECT
        (SELECT version_num FROM alembic_version ORDER BY version_num LIMIT 1),
        (SELECT count(*) FROM users),
        (SELECT count(*) FROM stories),
        (SELECT count(*) FROM messages)
    "
)"
verification="${verification//$'\n'/}"
[[ "$verification" == ?*'|'*'|'*'|'* ]] || {
  print -u2 "Restored database verification returned an invalid result"
  exit 1
}

restore_complete=1
elapsed_seconds="$(( $(date +%s) - started_at ))"
print "Restore verified: $TARGET_DATABASE"
print "revision|users|stories|messages: $verification"
print "elapsed_seconds: $elapsed_seconds"
if [[ "$DROP_AFTER_VERIFY" -eq 1 ]]; then
  print "Isolation database will be removed after verification"
fi
