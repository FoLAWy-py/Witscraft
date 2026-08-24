#!/bin/zsh
set -euo pipefail

umask 077

ROOT="${WITSCRAFT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
RUNTIME="${WITSCRAFT_STAGING_RUNTIME:-$ROOT/.runtime/staging}"
SOURCE_SECRETS="${WITSCRAFT_SECRETS_FILE:-$ROOT/.runtime/api.env}"
COMPOSE_FILE="$ROOT/ops/staging/compose.yml"
NGINX_TEMPLATE="$ROOT/ops/staging/nginx.conf.template"
PROXY_API_CONFIG="$ROOT/ops/staging/proxy-api.conf"
PROXY_WEB_CONFIG="$ROOT/ops/staging/proxy-web.conf"
RUNTIME_ENV="$RUNTIME/runtime.env"
NGINX_CONFIG="$RUNTIME/nginx.conf"
STAGING_SECRETS="$RUNTIME/api.env"
AGENT_DOMAIN="gui/$(id -u)"
AGENT_LABEL_PREFIX="com.witscraft.staging"

usage() {
  print "Usage: scripts/staging-release.sh <prepare|build|start|stop|status|smoke|verify-resilience|live-experience|observe|reset> [options]"
  print "  start [--skip-build]"
  print "  smoke --manifest /absolute/path/to/release.json"
  print "  live-experience --confirm-live-provider"
  print "  observe [--minutes 30]"
  print "  reset --confirm-staging-data-reset"
}

fail() {
  print -u2 "Staging release failed: $1"
  exit 1
}

require_command() {
  command -v "$1" >/dev/null || fail "required command is unavailable: $1"
}

validate_port() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ '^[0-9]+$' ]] || fail "$name must be an integer from 1 to 65535"
  (( value >= 1 && value <= 65535 )) || fail "$name must be an integer from 1 to 65535"
}

detect_lan_host() {
  local detected=""
  for interface in en0 en1; do
    detected="$(ipconfig getifaddr "$interface" 2>/dev/null || true)"
    if [[ -n "$detected" ]]; then
      print "$detected"
      return
    fi
  done
  detected="$(ifconfig en0 2>/dev/null | awk '$1 == "inet" { print $2; exit }')"
  if [[ -n "$detected" ]]; then
    print "$detected"
    return
  fi
  print "127.0.0.1"
}

detect_additional_lan_hosts() {
  local primary_host="$1"
  local -a detected_hosts
  detected_hosts=("${(@f)$(ifconfig 2>/dev/null | awk '$1 == "inet" { print $2 }' | sort -u)}")
  local host
  for host in "${detected_hosts[@]}"; do
    [[ "$host" == "$primary_host" || "$host" == "127.0.0.1" ]] && continue
    if [[ "$host" == 10.* || "$host" == 192.168.* || \
          "$host" =~ '^172\.(1[6-9]|2[0-9]|3[01])\.' ]]; then
      print "$host"
    fi
  done
}

default_additional_lan_hosts() {
  local primary_host="$1"
  local -a hosts
  hosts=("${(@f)$(detect_additional_lan_hosts "$primary_host")}")
  print "${(j:,:)hosts}"
}

validate_staging_hosts() {
  local host
  for host in "$STAGING_HOST" "${(@s:,:)STAGING_ADDITIONAL_HOSTS}"; do
    [[ -z "$host" ]] && continue
    [[ "$host" =~ '^[A-Za-z0-9.-]+$' ]] || fail "staging host contains unsafe characters"
  done
}

staging_hosts() {
  local host
  print "$STAGING_HOST"
  for host in "${(@s:,:)STAGING_ADDITIONAL_HOSTS}"; do
    [[ -z "$host" || "$host" == "$STAGING_HOST" ]] && continue
    print "$host"
  done
}

allowed_hosts_json() {
  local result='["localhost","127.0.0.1"'
  local host
  for host in "${(@f)$(staging_hosts)}"; do
    result+=',"'"$host"'"'
  done
  print "$result]"
}

trusted_origins_json() {
  local result='["https://localhost:'"$STAGING_GATEWAY_PORT"'"'
  local host
  for host in "${(@f)$(staging_hosts)}"; do
    result+=',"https://'"$host:$STAGING_GATEWAY_PORT"'"'
  done
  print "$result]"
}

write_runtime_env() {
  if [[ -f "$RUNTIME_ENV" ]]; then
    return
  fi
  local staging_host="${WITSCRAFT_STAGING_HOST:-$(detect_lan_host)}"
  [[ "$staging_host" =~ '^[A-Za-z0-9.-]+$' ]] || fail "staging host contains unsafe characters"
  local additional_hosts="${WITSCRAFT_STAGING_ADDITIONAL_HOSTS:-$(default_additional_lan_hosts "$staging_host")}"
  local database_password
  database_password="$(openssl rand -hex 24)"
  {
    print "STAGING_HOST=$staging_host"
    print "STAGING_ADDITIONAL_HOSTS=$additional_hosts"
    print "STAGING_GATEWAY_PORT=${WITSCRAFT_STAGING_GATEWAY_PORT:-19473}"
    print "STAGING_WEB_PORT=${WITSCRAFT_STAGING_WEB_PORT:-18321}"
    print "STAGING_API_PORT=${WITSCRAFT_STAGING_API_PORT:-18322}"
    print "STAGING_DATABASE_PORT=${WITSCRAFT_STAGING_DATABASE_PORT:-15432}"
    print "DATABASE_USERNAME=witscraft_staging"
    print "DATABASE_PASSWORD=$database_password"
    print "DATABASE_NAME=witscraft_staging"
    print "LAN_DATABASE_USERNAME=witscraft_lan_access"
    print "LAN_DATABASE_PASSWORD=$(openssl rand -hex 24)"
  } > "$RUNTIME_ENV"
  chmod 600 "$RUNTIME_ENV"
}

load_runtime_env() {
  [[ -r "$RUNTIME_ENV" ]] || fail "runtime environment is missing; run prepare first"
  set -a
  source "$RUNTIME_ENV"
  set +a
  if [[ -z "${LAN_DATABASE_USERNAME:-}" || -z "${LAN_DATABASE_PASSWORD:-}" ]]; then
    LAN_DATABASE_USERNAME=witscraft_lan_access
    LAN_DATABASE_PASSWORD="$(openssl rand -hex 24)"
    {
      print "LAN_DATABASE_USERNAME=$LAN_DATABASE_USERNAME"
      print "LAN_DATABASE_PASSWORD=$LAN_DATABASE_PASSWORD"
    } >> "$RUNTIME_ENV"
    chmod 600 "$RUNTIME_ENV"
    export LAN_DATABASE_USERNAME LAN_DATABASE_PASSWORD
  fi
  STAGING_ADDITIONAL_HOSTS="${STAGING_ADDITIONAL_HOSTS:-${WITSCRAFT_STAGING_ADDITIONAL_HOSTS:-$(default_additional_lan_hosts "$STAGING_HOST")}}"
  export STAGING_ADDITIONAL_HOSTS
  if ! grep -q '^STAGING_ADDITIONAL_HOSTS=' "$RUNTIME_ENV"; then
    print "STAGING_ADDITIONAL_HOSTS=$STAGING_ADDITIONAL_HOSTS" >> "$RUNTIME_ENV"
  fi
  if [[ "$STAGING_HOST" == "127.0.0.1" ]]; then
    local detected_host="$(detect_lan_host)"
    if [[ "$detected_host" != "127.0.0.1" ]]; then
      local temporary_env="$RUNTIME_ENV.tmp"
      sed "s/^STAGING_HOST=.*/STAGING_HOST=$detected_host/" "$RUNTIME_ENV" > "$temporary_env"
      chmod 600 "$temporary_env"
      mv "$temporary_env" "$RUNTIME_ENV"
      STAGING_HOST="$detected_host"
      export STAGING_HOST
    fi
  fi
  : "${STAGING_HOST:?STAGING_HOST is required}"
  : "${STAGING_GATEWAY_PORT:?STAGING_GATEWAY_PORT is required}"
  : "${STAGING_WEB_PORT:?STAGING_WEB_PORT is required}"
  : "${STAGING_API_PORT:?STAGING_API_PORT is required}"
  : "${STAGING_DATABASE_PORT:?STAGING_DATABASE_PORT is required}"
  : "${DATABASE_USERNAME:?DATABASE_USERNAME is required}"
  : "${DATABASE_PASSWORD:?DATABASE_PASSWORD is required}"
  : "${DATABASE_NAME:?DATABASE_NAME is required}"
  : "${LAN_DATABASE_USERNAME:?LAN_DATABASE_USERNAME is required}"
  : "${LAN_DATABASE_PASSWORD:?LAN_DATABASE_PASSWORD is required}"
  [[ "$DATABASE_USERNAME" =~ '^[A-Za-z0-9_]+$' ]] || fail "database username contains unsafe characters"
  [[ "$LAN_DATABASE_USERNAME" =~ '^[A-Za-z0-9_]+$' ]] || fail "LAN database username contains unsafe characters"
  [[ "$LAN_DATABASE_PASSWORD" =~ '^[A-Fa-f0-9]+$' ]] || fail "LAN database password is not generated safely"
  validate_staging_hosts
  validate_port STAGING_GATEWAY_PORT "$STAGING_GATEWAY_PORT"
  validate_port STAGING_WEB_PORT "$STAGING_WEB_PORT"
  validate_port STAGING_API_PORT "$STAGING_API_PORT"
  validate_port STAGING_DATABASE_PORT "$STAGING_DATABASE_PORT"
}

tls_subject_alt_name() {
  local result="DNS:localhost,IP:127.0.0.1"
  local host
  for host in "${(@f)$(staging_hosts)}"; do
    if [[ "$host" =~ '^[0-9]+(\.[0-9]+){3}$' ]]; then
      result+=",IP:$host"
    else
      result+=",DNS:$host"
    fi
  done
  print "$result"
}

prepare() {
  for command in docker nginx openssl sed; do
    require_command "$command"
  done
  mkdir -p "$RUNTIME/logs" "$RUNTIME/tls" "$RUNTIME/monitoring" "$RUNTIME/backups"
  chmod 700 "$RUNTIME" "$RUNTIME/logs" "$RUNTIME/tls" "$RUNTIME/monitoring" "$RUNTIME/backups"
  write_runtime_env
  load_runtime_env

  if [[ ! -f "$RUNTIME/tls/server.crt" || ! -f "$RUNTIME/tls/server.key" || \
        ! -f "$RUNTIME/tls/host" || "$(<"$RUNTIME/tls/host")" != "$STAGING_HOST,$STAGING_ADDITIONAL_HOSTS" ]]; then
    openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 30 \
      -keyout "$RUNTIME/tls/server.key" \
      -out "$RUNTIME/tls/server.crt" \
      -subj "/CN=$STAGING_HOST" \
      -addext "subjectAltName=$(tls_subject_alt_name)" \
      -addext "basicConstraints=critical,CA:TRUE" >/dev/null 2>&1
    chmod 600 "$RUNTIME/tls/server.key" "$RUNTIME/tls/server.crt"
    print "$STAGING_HOST,$STAGING_ADDITIONAL_HOSTS" > "$RUNTIME/tls/host"
    chmod 600 "$RUNTIME/tls/host"
  fi

  sed \
    -e "s/__STAGING_GATEWAY_PORT__/$STAGING_GATEWAY_PORT/g" \
    -e "s/__STAGING_API_PORT__/$STAGING_API_PORT/g" \
    -e "s/__STAGING_WEB_PORT__/$STAGING_WEB_PORT/g" \
    "$NGINX_TEMPLATE" > "$NGINX_CONFIG"
  cp "$PROXY_API_CONFIG" "$RUNTIME/proxy-api.conf"
  cp "$PROXY_WEB_CONFIG" "$RUNTIME/proxy-web.conf"
  chmod 600 "$NGINX_CONFIG" "$RUNTIME/proxy-api.conf" "$RUNTIME/proxy-web.conf"
  nginx -t -p "$RUNTIME/" -c "$NGINX_CONFIG"
  print "Staging runtime prepared under $RUNTIME"
  print "Gateway class: local-area-network TLS"
}

runtime_env_command() {
  configure_runtime_environment
  "$@"
}

configure_runtime_environment() {
  local allowed_hosts="$(allowed_hosts_json)"
  local trusted_origins="$(trusted_origins_json)"
  export APP_ENVIRONMENT=production
  export WITSCRAFT_SECRETS_FILE="$SOURCE_SECRETS"
  export DATABASE_USERNAME DATABASE_PASSWORD DATABASE_NAME
  export DATABASE_HOST=127.0.0.1
  export DATABASE_PORT="$STAGING_DATABASE_PORT"
  export FRONTEND_BASE_URL="https://$STAGING_HOST:$STAGING_GATEWAY_PORT/witscraft"
  export ALLOWED_HOSTS="$allowed_hosts"
  export CORS_ORIGINS="$trusted_origins"
  export CORS_ORIGIN_REGEX=
  export CSRF_TRUSTED_ORIGINS="$trusted_origins"
  export AUTH_COOKIE_SECURE=true
  export RATE_LIMIT_ENABLED=true
  export OPERATIONAL_METRICS_LOG_PATH="$RUNTIME/access-metrics.log"
  export UV_CACHE_DIR="${WITSCRAFT_UV_CACHE_DIR:-/tmp/witscraft-staging-uv-cache}"
}

write_staging_secrets() {
  local mode="${1:-normal}"
  [[ "$mode" == "normal" || "$mode" == "bounded" ]] || fail "unknown staging secrets mode"
  [[ "$SOURCE_SECRETS" != "$STAGING_SECRETS" ]] || fail "source and staging secrets paths must differ"
  local temporary_secrets="$STAGING_SECRETS.tmp"
  local allowed_hosts="$(allowed_hosts_json)"
  local trusted_origins="$(trusted_origins_json)"
  cp "$SOURCE_SECRETS" "$temporary_secrets"
  {
    print ""
    print "# Isolated staging overrides generated by scripts/staging-release.sh"
    print "APP_ENVIRONMENT=production"
    print "DATABASE_USERNAME=$DATABASE_USERNAME"
    print "DATABASE_PASSWORD=$DATABASE_PASSWORD"
    print "DATABASE_HOST=127.0.0.1"
    print "DATABASE_PORT=$STAGING_DATABASE_PORT"
    print "DATABASE_NAME=$DATABASE_NAME"
    print "FRONTEND_BASE_URL=https://$STAGING_HOST:$STAGING_GATEWAY_PORT/witscraft"
    print "ALLOWED_HOSTS=$allowed_hosts"
    print "CORS_ORIGINS=$trusted_origins"
    print "CORS_ORIGIN_REGEX="
    print "CSRF_TRUSTED_ORIGINS=$trusted_origins"
    print "AUTH_COOKIE_SECURE=true"
    print "RATE_LIMIT_ENABLED=true"
    print "OPERATIONAL_METRICS_LOG_PATH=$RUNTIME/access-metrics.log"
    if [[ "$mode" == "bounded" ]]; then
      print "LLM_MAX_ATTEMPTS=1"
      print "LLM_MAX_FALLBACKS=0"
    fi
  } >> "$temporary_secrets"
  chmod 600 "$temporary_secrets"
  mv "$temporary_secrets" "$STAGING_SECRETS"
}

render_launch_agents() {
  local uv_path="$(command -v uv)"
  local npm_path="$(command -v npm)"
  local executable_path="$(dirname "$npm_path"):$(dirname "$uv_path"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
  local template output
  for service in api worker web; do
    template="$ROOT/ops/staging/$AGENT_LABEL_PREFIX.$service.plist.template"
    output="$RUNTIME/$AGENT_LABEL_PREFIX.$service.plist"
    sed \
      -e "s|__UV_PATH__|$uv_path|g" \
      -e "s|__NPM_PATH__|$npm_path|g" \
      -e "s|__EXECUTABLE_PATH__|$executable_path|g" \
      -e "s|__UV_CACHE_DIRECTORY__|${WITSCRAFT_UV_CACHE_DIR:-/tmp/witscraft-staging-uv-cache}|g" \
      -e "s|__API_DIRECTORY__|$ROOT/apps/api|g" \
      -e "s|__WEB_DIRECTORY__|$ROOT/apps/web|g" \
      -e "s|__WORKER_SCRIPT__|$ROOT/scripts/run-memory-embedding-worker.py|g" \
      -e "s|__STAGING_SECRETS_FILE__|$STAGING_SECRETS|g" \
      -e "s|__LOG_DIRECTORY__|$RUNTIME/logs|g" \
      -e "s|__STAGING_API_PORT__|$STAGING_API_PORT|g" \
      -e "s|__STAGING_WEB_PORT__|$STAGING_WEB_PORT|g" \
      "$template" > "$output"
    chmod 600 "$output"
    plutil -lint "$output" >/dev/null
  done
}

agent_loaded() {
  launchctl print "$AGENT_DOMAIN/$1" >/dev/null 2>&1
}

agent_running() {
  launchctl print "$AGENT_DOMAIN/$1" 2>/dev/null | grep -q 'state = running'
}

agent_pid() {
  launchctl print "$AGENT_DOMAIN/$1" 2>/dev/null | \
    awk '$1 == "pid" && $2 == "=" { print $3; exit }'
}

start_agent() {
  local service="$1"
  local label="$AGENT_LABEL_PREFIX.$service"
  local plist="$RUNTIME/$label.plist"
  if agent_loaded "$label"; then
    launchctl bootout "$AGENT_DOMAIN/$label"
    local attempt
    for (( attempt = 1; attempt <= 30; attempt++ )); do
      agent_loaded "$label" || break
      sleep 0.2
    done
    agent_loaded "$label" && fail "$label did not unload before restart"
  fi
  launchctl bootstrap "$AGENT_DOMAIN" "$plist"
}

stop_agent() {
  local label="$AGENT_LABEL_PREFIX.$1"
  if agent_loaded "$label"; then
    launchctl bootout "$AGENT_DOMAIN/$label"
  fi
}

compose() {
  docker compose \
    --project-name witscraft-staging \
    --env-file "$RUNTIME_ENV" \
    --file "$COMPOSE_FILE" \
    "$@"
}

configure_lan_database_access() {
  compose exec --no-TTY postgres psql \
    --username "$DATABASE_USERNAME" \
    --dbname "$DATABASE_NAME" \
    --set=lan_role="$LAN_DATABASE_USERNAME" \
    --set=lan_password="$LAN_DATABASE_PASSWORD" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L',
  :'lan_role', :'lan_password'
) WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'lan_role') \gexec
SELECT format(
  'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L',
  :'lan_role', :'lan_password'
) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'lan_role') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'lan_role') \gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', :'lan_role') \gexec
SELECT format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO %I', :'lan_role') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'lan_role') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I', :'lan_role') \gexec
SQL

  local temporary_certificate="$RUNTIME/tls/postgres-server.crt.tmp"
  compose cp postgres:/var/lib/postgresql/tls/server.crt "$temporary_certificate" >/dev/null
  openssl x509 -in "$temporary_certificate" -noout -checkend 0 >/dev/null
  chmod 600 "$temporary_certificate"
  mv "$temporary_certificate" "$RUNTIME/tls/postgres-server.crt"

  local temporary_credentials="$RUNTIME/database-client.env.tmp"
  {
    print "PGHOST=$STAGING_HOST"
    print "PGALTERNATEHOSTS=$STAGING_ADDITIONAL_HOSTS"
    print "PGPORT=$STAGING_DATABASE_PORT"
    print "PGDATABASE=$DATABASE_NAME"
    print "PGUSER=$LAN_DATABASE_USERNAME"
    print "PGPASSWORD=$LAN_DATABASE_PASSWORD"
    print "PGSSLMODE=verify-full"
    print "PGSSLROOTCERT=postgres-server.crt"
  } > "$temporary_credentials"
  chmod 600 "$temporary_credentials"
  mv "$temporary_credentials" "$RUNTIME/database-client.env"
}

build_web() {
  require_command npm
  cd "$ROOT/apps/web"
  NEXT_PUBLIC_BASE_PATH=/witscraft NEXT_PUBLIC_API_BASE_URL=/witscraft npm run build
  git -C "$ROOT" rev-parse HEAD > "$RUNTIME/web-build-revision"
  chmod 600 "$RUNTIME/web-build-revision"
}

wait_for_url() {
  local url="$1"
  local attempts="${2:-60}"
  local attempt
  for (( attempt = 1; attempt <= attempts; attempt++ )); do
    if curl --silent --show-error --fail --location --max-redirs 5 \
      --cacert "$RUNTIME/tls/server.crt" "$url" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  fail "service did not become ready: $url"
}

wait_for_api_stopped() {
  local attempt
  for (( attempt = 1; attempt <= 30; attempt++ )); do
    if ! nc -z 127.0.0.1 "$STAGING_API_PORT" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  fail "API did not stop within its graceful shutdown window"
}

nginx_running() {
  [[ -r "$RUNTIME/nginx.pid" ]] || return 1
  local pid="$(<"$RUNTIME/nginx.pid")"
  [[ "$pid" == <-> ]] && kill -0 "$pid" 2>/dev/null
}

start() {
  local skip_build=false
  local start_complete=false
  cleanup_failed_start() {
    if [[ "$start_complete" == false ]]; then
      print -u2 "Staging start did not complete; cleaning up isolated processes"
      stop >/dev/null 2>&1 || true
    fi
  }
  trap cleanup_failed_start EXIT INT TERM
  if [[ "${1:-}" == "--skip-build" ]]; then
    skip_build=true
    shift
  fi
  [[ "$#" -eq 0 ]] || fail "unexpected start arguments"
  prepare
  load_runtime_env
  [[ -r "$SOURCE_SECRETS" ]] || fail "production-shaped source secrets file is not readable"
  [[ "$(stat -f %Lp "$SOURCE_SECRETS")" == "600" ]] || fail "source secrets file must have mode 600"
  for command in curl docker nginx npm uv; do
    require_command "$command"
  done

  compose up --detach --wait
  cd "$ROOT/apps/api"
  runtime_env_command uv run alembic upgrade head
  runtime_env_command uv run alembic check
  configure_lan_database_access
  runtime_env_command uv run python -c \
    "from app.config import get_settings, validate_runtime_security; validate_runtime_security(get_settings())"
  write_staging_secrets

  if [[ "$skip_build" == false ]]; then
    build_web
  elif [[ ! -r "$ROOT/apps/web/.next/BUILD_ID" ]]; then
    fail "--skip-build requires an existing production build"
  fi
  python3 "$ROOT/scripts/create-release-manifest.py" --output "$RUNTIME/candidate.json"

  render_launch_agents
  start_agent api
  start_agent worker
  start_agent web

  if nginx_running; then
    nginx -p "$RUNTIME/" -c "$NGINX_CONFIG" -s reload
  else
    nginx -p "$RUNTIME/" -c "$NGINX_CONFIG"
  fi
  wait_for_url "https://localhost:$STAGING_GATEWAY_PORT/witscraft/health/ready"
  wait_for_url "https://localhost:$STAGING_GATEWAY_PORT/witscraft/"
  start_complete=true
  trap - EXIT INT TERM
  print "Staging release candidate is ready at https://$STAGING_HOST:$STAGING_GATEWAY_PORT/witscraft/"
  print "Trust only the runtime certificate for this isolated test; do not expose this endpoint publicly."
}

stop() {
  if [[ -r "$NGINX_CONFIG" ]]; then
    nginx -p "$RUNTIME/" -c "$NGINX_CONFIG" -s quit 2>/dev/null || true
  fi
  stop_agent web || true
  stop_agent worker || true
  stop_agent api || true
  if [[ -r "$RUNTIME_ENV" ]]; then
    load_runtime_env
    compose down
  fi
  print "Staging processes stopped; isolated database volume retained"
}

status() {
  load_runtime_env
  local failed=0
  for service in api worker web; do
    if agent_running "$AGENT_LABEL_PREFIX.$service"; then
      print "$service: running"
    else
      print "$service: stopped"
      failed=1
    fi
  done
  if curl --silent --show-error --fail --cacert "$RUNTIME/tls/server.crt" \
    "https://localhost:$STAGING_GATEWAY_PORT/witscraft/health/ready" >/dev/null; then
    print "gateway: ready"
  else
    print "gateway: not ready"
    failed=1
  fi
  compose ps
  return "$failed"
}

wait_for_agent_restart() {
  local label="$1"
  local previous_pid="$2"
  local attempt current_pid
  for (( attempt = 1; attempt <= 30; attempt++ )); do
    current_pid="$(agent_pid "$label")"
    if [[ -n "$current_pid" && "$current_pid" != "$previous_pid" ]] && agent_running "$label"; then
      return
    fi
    sleep 1
  done
  fail "$label did not restart under launchd supervision"
}

verify_resilience() {
  load_runtime_env
  for command in curl grep nc nginx python3; do
    require_command "$command"
  done
  status >/dev/null || fail "staging must be healthy before resilience verification"

  local evidence_dir="$RUNTIME/resilience"
  local api_body="$evidence_dir/api-unavailable.json"
  local api_headers="$evidence_dir/api-unavailable.headers"
  local timeout_body="$evidence_dir/api-timeout.json"
  local timeout_headers="$evidence_dir/api-timeout.headers"
  local ready_file="$evidence_dir/slow-upstream.ready"
  local original_proxy="$evidence_dir/proxy-api.original.conf"
  local slow_pid=""
  local recovery_complete=false
  mkdir -p "$evidence_dir"
  chmod 700 "$evidence_dir"
  cp "$RUNTIME/proxy-api.conf" "$original_proxy"
  chmod 600 "$original_proxy"

  restore_resilience_services() {
    if [[ -n "${slow_pid:-}" ]]; then
      kill "${slow_pid}" 2>/dev/null || true
      wait "${slow_pid}" 2>/dev/null || true
      slow_pid=""
    fi
    if [[ -r "${original_proxy:-}" ]]; then
      cp "${original_proxy}" "$RUNTIME/proxy-api.conf"
    fi
    nginx -t -p "$RUNTIME/" -c "$NGINX_CONFIG" >/dev/null 2>&1 || true
    nginx -p "$RUNTIME/" -c "$NGINX_CONFIG" -s reload 2>/dev/null || true
    compose up --detach --wait >/dev/null 2>&1 || true
    if ! agent_loaded "$AGENT_LABEL_PREFIX.api"; then
      start_agent api >/dev/null 2>&1 || true
    fi
    [[ "${recovery_complete:-false}" == true ]] || \
      print -u2 "Resilience cleanup restored service supervision"
  }
  trap restore_resilience_services EXIT INT TERM

  stop_agent api
  wait_for_api_stopped
  local unavailable_status
  unavailable_status="$(curl --silent --show-error \
    --cacert "$RUNTIME/tls/server.crt" \
    --dump-header "$api_headers" --output "$api_body" --write-out '%{http_code}' \
    "https://localhost:$STAGING_GATEWAY_PORT/witscraft/api/providers")"
  [[ "$unavailable_status" == "503" ]] || fail "gateway outage contract returned HTTP $unavailable_status"
  grep -qi '^Retry-After: 5' "$api_headers" || fail "gateway outage response omitted Retry-After"
  grep -q 'Your story was not changed' "$api_body" || fail "gateway outage response omitted recovery guidance"

  sed 's/proxy_read_timeout 900s;/proxy_read_timeout 1s;/' \
    "$original_proxy" > "$RUNTIME/proxy-api.conf"
  chmod 600 "$RUNTIME/proxy-api.conf"
  nginx -t -p "$RUNTIME/" -c "$NGINX_CONFIG" >/dev/null
  nginx -p "$RUNTIME/" -c "$NGINX_CONFIG" -s reload
  rm -f "$ready_file"
  python3 "$ROOT/scripts/staging-slow-upstream.py" \
    --host 127.0.0.1 --port "$STAGING_API_PORT" --delay 3 --ready-file "$ready_file" &
  slow_pid=$!
  local attempt
  for (( attempt = 1; attempt <= 20; attempt++ )); do
    [[ -r "$ready_file" ]] && break
    sleep 0.1
  done
  [[ -r "$ready_file" ]] || fail "slow loopback upstream did not become ready"

  local timeout_status
  timeout_status="$(curl --silent --show-error \
    --cacert "$RUNTIME/tls/server.crt" \
    --dump-header "$timeout_headers" --output "$timeout_body" --write-out '%{http_code}' \
    "https://localhost:$STAGING_GATEWAY_PORT/witscraft/api/providers")"
  [[ "$timeout_status" == "503" ]] || fail "gateway timeout contract returned HTTP $timeout_status"
  grep -qi '^Retry-After: 5' "$timeout_headers" || fail "gateway timeout response omitted Retry-After"
  wait "$slow_pid" 2>/dev/null || true
  slow_pid=""
  cp "$original_proxy" "$RUNTIME/proxy-api.conf"
  nginx -t -p "$RUNTIME/" -c "$NGINX_CONFIG" >/dev/null
  nginx -p "$RUNTIME/" -c "$NGINX_CONFIG" -s reload

  start_agent api
  wait_for_url "https://localhost:$STAGING_GATEWAY_PORT/witscraft/health/ready"
  local first_pid="$(agent_pid "$AGENT_LABEL_PREFIX.api")"
  [[ -n "$first_pid" ]] || fail "API launchd job has no process ID"
  launchctl kill SIGKILL "$AGENT_DOMAIN/$AGENT_LABEL_PREFIX.api"
  wait_for_agent_restart "$AGENT_LABEL_PREFIX.api" "$first_pid"
  wait_for_url "https://localhost:$STAGING_GATEWAY_PORT/witscraft/health/ready"

  compose stop postgres >/dev/null
  local database_outage_status
  database_outage_status="$(curl --silent --show-error \
    --cacert "$RUNTIME/tls/server.crt" --output "$evidence_dir/database-outage.json" \
    --write-out '%{http_code}' \
    "https://localhost:$STAGING_GATEWAY_PORT/witscraft/health/ready")"
  [[ "$database_outage_status" == "503" ]] || \
    fail "database outage readiness returned HTTP $database_outage_status"
  compose up --detach --wait >/dev/null
  wait_for_url "https://localhost:$STAGING_GATEWAY_PORT/witscraft/health/ready"

  {
    print '{'
    print '  "schema_version": "staging-resilience-v1",'
    print '  "api_upstream_unavailable_status": 503,'
    print '  "api_upstream_timeout_status": 503,'
    print '  "database_outage_readiness_status": 503,'
    print '  "api_launchd_restart": "passed",'
    print '  "post_recovery_readiness": "passed"'
    print '}'
  } > "$evidence_dir/report.json"
  chmod 600 "$evidence_dir"/*
  recovery_complete=true
  trap - EXIT INT TERM
  print "Staging resilience verification passed: unavailable, timeout, restart, database outage, and recovery"
}

live_experience() {
  [[ "${1:-}" == "--confirm-live-provider" && "$#" -eq 1 ]] || \
    fail "live-experience requires --confirm-live-provider"
  load_runtime_env
  status >/dev/null || fail "staging must be healthy before live-provider validation"
  local restored=false
  restore_live_configuration() {
    if [[ "${restored:-false}" == false ]]; then
      write_staging_secrets normal
      start_agent api >/dev/null 2>&1 || true
      start_agent worker >/dev/null 2>&1 || true
      restored=true
    fi
  }
  trap restore_live_configuration EXIT INT TERM

  stop_agent worker
  write_staging_secrets bounded
  start_agent api
  wait_for_url "https://localhost:$STAGING_GATEWAY_PORT/witscraft/health/ready"
  export LLM_MAX_ATTEMPTS=1
  export LLM_MAX_FALLBACKS=0
  runtime_env_command uv run --directory "$ROOT/apps/api" python \
    "$ROOT/scripts/capture-staging-experience.py" \
    "https://localhost:$STAGING_GATEWAY_PORT/witscraft" \
    --ca-file "$RUNTIME/tls/server.crt" \
    --output "$RUNTIME/provider-experience.json" \
    --confirm-live-provider

  write_staging_secrets normal
  start_agent api
  start_agent worker
  wait_for_url "https://localhost:$STAGING_GATEWAY_PORT/witscraft/health/ready"
  restored=true
  trap - EXIT INT TERM
  print "Normal staging retry/fallback configuration restored after bounded provider validation"
}

smoke() {
  [[ "${1:-}" == "--manifest" && -n "${2:-}" && "$#" -eq 2 ]] || \
    fail "smoke requires --manifest /absolute/path/to/release.json"
  local manifest="$2"
  [[ "$manifest" == /* && -r "$manifest" ]] || fail "manifest must be an absolute readable path"
  load_runtime_env
  python3 "$ROOT/scripts/smoke-release.py" \
    "https://localhost:$STAGING_GATEWAY_PORT/witscraft" \
    --manifest "$manifest" \
    --ca-file "$RUNTIME/tls/server.crt"
}

observe() {
  local minutes=30
  if [[ "$#" -gt 0 ]]; then
    [[ "${1:-}" == "--minutes" && "${2:-}" == <-> && "$#" -eq 2 ]] || \
      fail "observe accepts only --minutes <5-60>"
    minutes="$2"
  fi
  (( minutes >= 5 && minutes <= 60 )) || fail "observe minutes must be from 5 to 60"
  load_runtime_env
  status >/dev/null || fail "staging must be healthy before observation"
  python3 "$ROOT/scripts/observe-staging.py" \
    "https://$STAGING_HOST:$STAGING_GATEWAY_PORT/witscraft" \
    --ca-file "$RUNTIME/tls/server.crt" \
    --output "$RUNTIME/observation.json" \
    --minutes "$minutes"
}

reset_staging_data() {
  [[ "${1:-}" == "--confirm-staging-data-reset" && "$#" -eq 1 ]] || \
    fail "reset requires --confirm-staging-data-reset"
  [[ -r "$RUNTIME_ENV" ]] || fail "staging runtime is not prepared"
  load_runtime_env
  [[ "$DATABASE_NAME" == "witscraft_staging" ]] || fail "refusing to reset an unexpected database"
  stop
  compose down --volumes
  print "Removed only the witscraft-staging PostgreSQL volume"
}

command_name="${1:-}"
[[ -n "$command_name" ]] || {
  usage
  exit 2
}
shift

case "$command_name" in
  prepare) [[ "$#" -eq 0 ]] || fail "prepare takes no arguments"; prepare ;;
  build) [[ "$#" -eq 0 ]] || fail "build takes no arguments"; prepare; build_web ;;
  start) start "$@" ;;
  stop) [[ "$#" -eq 0 ]] || fail "stop takes no arguments"; stop ;;
  status) [[ "$#" -eq 0 ]] || fail "status takes no arguments"; status ;;
  smoke) smoke "$@" ;;
  verify-resilience) [[ "$#" -eq 0 ]] || fail "verify-resilience takes no arguments"; verify_resilience ;;
  live-experience) live_experience "$@" ;;
  observe) observe "$@" ;;
  reset) reset_staging_data "$@" ;;
  *) usage; exit 2 ;;
esac
