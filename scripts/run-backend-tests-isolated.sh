#!/bin/zsh
set -euo pipefail

umask 077

ROOT="${WITSCRAFT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SECRETS_FILE="${WITSCRAFT_SECRETS_FILE:-$ROOT/.runtime/api.env}"

[[ -r "$SECRETS_FILE" ]] || {
  print -u2 "Backend test secrets file is not readable"
  exit 1
}
for command in createdb dropdb; do
  command -v "$command" >/dev/null || {
    print -u2 "Required PostgreSQL test command is unavailable: $command"
    exit 1
  }
done

set -a
source "$SECRETS_FILE"
set +a

: "${DATABASE_USERNAME:?DATABASE_USERNAME is required}"
: "${DATABASE_PASSWORD:?DATABASE_PASSWORD is required}"
TEST_DATABASE_USERNAME="$DATABASE_USERNAME"
TEST_DATABASE_PASSWORD="$DATABASE_PASSWORD"
TEST_DATABASE_HOST="${DATABASE_HOST:-localhost}"
TEST_DATABASE_PORT="${DATABASE_PORT:-5432}"
BASE_DATABASE_NAME="${DATABASE_NAME:-witscraft}"

# The production secrets file is used only to obtain PostgreSQL connection
# details. Do not let unrelated production settings leak into pytest.
while IFS='=' read -r key _value; do
  key="${key##[[:space:]]#}"
  [[ "$key" =~ '^[A-Za-z_][A-Za-z0-9_]*$' ]] && unset "$key"
done < "$SECRETS_FILE"
unset WITSCRAFT_SECRETS_FILE

export DATABASE_USERNAME="$TEST_DATABASE_USERNAME"
export DATABASE_PASSWORD="$TEST_DATABASE_PASSWORD"
export DATABASE_HOST="$TEST_DATABASE_HOST"
export DATABASE_PORT="$TEST_DATABASE_PORT"
TEST_DATABASE_NAME="witscraft_preflight_test_${$}_$(date -u +%s)"
[[ "$TEST_DATABASE_NAME" != *[^a-zA-Z0-9_]* ]] || {
  print -u2 "Generated test database name is invalid"
  exit 1
}
[[ "$TEST_DATABASE_NAME" != "$BASE_DATABASE_NAME" ]] || {
  print -u2 "Refusing to use the configured database as the test database"
  exit 1
}

export PGPASSWORD="$TEST_DATABASE_PASSWORD"
cleanup() {
  dropdb \
    --host "$TEST_DATABASE_HOST" \
    --port "$TEST_DATABASE_PORT" \
    --username "$TEST_DATABASE_USERNAME" \
    --force \
    --if-exists \
    "$TEST_DATABASE_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

createdb \
  --host "$TEST_DATABASE_HOST" \
  --port "$TEST_DATABASE_PORT" \
  --username "$TEST_DATABASE_USERNAME" \
  --template template0 \
  "$TEST_DATABASE_NAME"

export APP_ENVIRONMENT=test
export DATABASE_NAME="$TEST_DATABASE_NAME"

cd "$ROOT/apps/api"
uv run alembic upgrade head
if [[ "$#" -eq 0 ]]; then
  uv run pytest -q
else
  uv run pytest "$@"
fi
