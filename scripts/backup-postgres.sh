#!/bin/zsh
set -euo pipefail

umask 077

ROOT="${WITSCRAFT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SECRETS_FILE="${WITSCRAFT_SECRETS_FILE:-$ROOT/.runtime/api.env}"
BACKUP_DIR="${WITSCRAFT_BACKUP_DIR:-$ROOT/.runtime/backups}"
RECIPIENT_CERT="${WITSCRAFT_BACKUP_CERT:-$ROOT/.runtime/backup-recipient.pem}"
OFFSITE_DIR="${WITSCRAFT_BACKUP_OFFSITE_DIR:-}"
LOCAL_RETENTION_DAYS="${WITSCRAFT_BACKUP_LOCAL_RETENTION_DAYS:-7}"
OFFSITE_RETENTION_DAYS="${WITSCRAFT_BACKUP_OFFSITE_RETENTION_DAYS:-35}"

for command in pg_dump psql openssl shasum; do
  command -v "$command" >/dev/null || {
    print -u2 "Required command is unavailable: $command"
    exit 1
  }
done

[[ -r "$SECRETS_FILE" ]] || {
  print -u2 "Database secrets file is not readable: $SECRETS_FILE"
  exit 1
}
[[ -r "$RECIPIENT_CERT" ]] || {
  print -u2 "Backup recipient certificate is not readable: $RECIPIENT_CERT"
  exit 1
}
[[ "$LOCAL_RETENTION_DAYS" == <-> && "$OFFSITE_RETENTION_DAYS" == <-> ]] || {
  print -u2 "Backup retention values must be non-negative integers"
  exit 1
}

set -a
source "$SECRETS_FILE"
set +a

: "${DATABASE_USERNAME:?DATABASE_USERNAME is required}"
: "${DATABASE_PASSWORD:?DATABASE_PASSWORD is required}"
DATABASE_HOST="${DATABASE_HOST:-localhost}"
DATABASE_PORT="${DATABASE_PORT:-5432}"
DATABASE_NAME="${DATABASE_NAME:-witscraft}"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

LOCK_DIR="$BACKUP_DIR/.backup.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  print -u2 "Another backup is already running: $LOCK_DIR"
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
base_name="witscraft-$timestamp"
partial_artifact="$BACKUP_DIR/.$base_name.dump.cms.partial"
artifact="$BACKUP_DIR/$base_name.dump.cms"
checksum_file="$artifact.sha256"
manifest_file="$artifact.json"

cleanup() {
  rm -f "$partial_artifact" "$checksum_file.partial" "$manifest_file.partial"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

export PGPASSWORD="$DATABASE_PASSWORD"
schema_revision="$(
  psql \
    --host "$DATABASE_HOST" \
    --port "$DATABASE_PORT" \
    --username "$DATABASE_USERNAME" \
    --dbname "$DATABASE_NAME" \
    --no-psqlrc --tuples-only --no-align \
    --command "SELECT version_num FROM alembic_version ORDER BY version_num LIMIT 1"
)"
schema_revision="${schema_revision//$'\n'/}"

pg_dump \
  --host "$DATABASE_HOST" \
  --port "$DATABASE_PORT" \
  --username "$DATABASE_USERNAME" \
  --dbname "$DATABASE_NAME" \
  --format custom \
  --compress zstd:9 \
  --no-owner \
  --no-acl \
  | openssl cms \
      -encrypt \
      -binary \
      -aes-256-gcm \
      -outform DER \
      -out "$partial_artifact" \
      "$RECIPIENT_CERT"

artifact_bytes="$(stat -f %z "$partial_artifact")"
[[ "$artifact_bytes" -ge 1024 ]] || {
  print -u2 "Encrypted backup is unexpectedly small: $artifact_bytes bytes"
  exit 1
}
openssl cms -cmsout -inform DER -in "$partial_artifact" -noout
mv "$partial_artifact" "$artifact"

checksum="$(shasum -a 256 "$artifact" | awk '{print $1}')"
printf '%s  %s\n' "$checksum" "$(basename "$artifact")" > "$checksum_file.partial"
mv "$checksum_file.partial" "$checksum_file"

git_revision="$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || print unknown)"
cat > "$manifest_file.partial" <<EOF
{
  "created_at_utc": "$timestamp",
  "artifact": "$(basename "$artifact")",
  "artifact_bytes": $artifact_bytes,
  "sha256": "$checksum",
  "format": "postgresql-custom-v1",
  "compression": "zstd-9",
  "encryption": "CMS-AES-256-GCM",
  "schema_revision": "$schema_revision",
  "application_revision": "$git_revision"
}
EOF
mv "$manifest_file.partial" "$manifest_file"

copy_replica() {
  local destination="$1"
  mkdir -p "$destination"
  chmod 700 "$destination" 2>/dev/null || true
  for source_file in "$artifact" "$checksum_file" "$manifest_file"; do
    local destination_file="$destination/$(basename "$source_file")"
    cp "$source_file" "$destination_file.partial"
    mv "$destination_file.partial" "$destination_file"
  done
}

if [[ -n "$OFFSITE_DIR" ]]; then
  copy_replica "$OFFSITE_DIR"
fi

prune_backups() {
  local directory="$1"
  local retention_days="$2"
  [[ -d "$directory" ]] || return 0
  find "$directory" -type f \
    \( -name 'witscraft-*.dump.cms' -o -name 'witscraft-*.dump.cms.sha256' \
       -o -name 'witscraft-*.dump.cms.json' \) \
    -mtime "+$retention_days" -delete
}

prune_backups "$BACKUP_DIR" "$LOCAL_RETENTION_DAYS"
if [[ -n "$OFFSITE_DIR" ]]; then
  prune_backups "$OFFSITE_DIR" "$OFFSITE_RETENTION_DAYS"
fi

print "Backup completed: $artifact"
print "Schema revision: $schema_revision"
print "Encrypted bytes: $artifact_bytes"
if [[ -n "$OFFSITE_DIR" ]]; then
  print "Replica completed: $OFFSITE_DIR/$(basename "$artifact")"
else
  print "Replica skipped: WITSCRAFT_BACKUP_OFFSITE_DIR is not configured"
fi
