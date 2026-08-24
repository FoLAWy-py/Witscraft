#!/usr/bin/env bash
set -Eeuo pipefail

certificate_directory=/var/lib/postgresql/tls
certificate_file="$certificate_directory/server.crt"
key_file="$certificate_directory/server.key"
host_marker="$certificate_directory/hosts"
expected_hosts="${STAGING_HOST},${STAGING_ADDITIONAL_HOSTS:-}"

validate_host() {
  [[ "$1" =~ ^[A-Za-z0-9.-]+$ ]] || {
    echo "Invalid staging database TLS host" >&2
    exit 1
  }
}

subject_alt_name="DNS:localhost,IP:127.0.0.1"
IFS=',' read -ra database_hosts <<< "$expected_hosts"
for host in "${database_hosts[@]}"; do
  [[ -z "$host" ]] && continue
  validate_host "$host"
  if [[ "$host" =~ ^[0-9]+(\.[0-9]+){3}$ ]]; then
    subject_alt_name+=",IP:$host"
  else
    subject_alt_name+=",DNS:$host"
  fi
done

mkdir -p "$certificate_directory"
if [[ ! -s "$certificate_file" || ! -s "$key_file" || ! -s "$host_marker" || \
      "$(<"$host_marker")" != "$expected_hosts" ]] || \
      ! openssl x509 -checkend 86400 -noout -in "$certificate_file" >/dev/null 2>&1; then
  temporary_directory="$(mktemp -d "$certificate_directory/new.XXXXXX")"
  trap 'rm -rf "$temporary_directory"' EXIT
  openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 30 \
    -keyout "$temporary_directory/server.key" \
    -out "$temporary_directory/server.crt" \
    -subj "/CN=$STAGING_HOST" \
    -addext "subjectAltName=$subject_alt_name" \
    -addext "basicConstraints=critical,CA:TRUE" >/dev/null 2>&1
  printf '%s\n' "$expected_hosts" > "$temporary_directory/hosts"
  chown postgres:postgres "$temporary_directory/server.key" \
    "$temporary_directory/server.crt" "$temporary_directory/hosts"
  chmod 600 "$temporary_directory/server.key"
  chmod 644 "$temporary_directory/server.crt" "$temporary_directory/hosts"
  mv "$temporary_directory/server.key" "$key_file"
  mv "$temporary_directory/server.crt" "$certificate_file"
  mv "$temporary_directory/hosts" "$host_marker"
  rmdir "$temporary_directory"
  trap - EXIT
fi

chown postgres:postgres "$certificate_directory" "$certificate_file" "$key_file" "$host_marker"
chmod 700 "$certificate_directory"
chmod 600 "$key_file"

exec /usr/local/bin/docker-entrypoint.sh postgres \
  -c listen_addresses='*' \
  -c password_encryption=scram-sha-256 \
  -c ssl=on \
  -c ssl_cert_file="$certificate_file" \
  -c ssl_key_file="$key_file" \
  -c hba_file=/etc/postgresql/witscraft-pg_hba.conf
