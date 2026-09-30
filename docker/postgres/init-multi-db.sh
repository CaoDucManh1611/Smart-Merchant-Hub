#!/bin/sh
set -eu

create_database_if_missing() {
  database_name="$1"
  host_args=""
  if [ -n "${PGHOST:-}" ]; then
    host_args="--host=$PGHOST"
  fi
  exists="$(psql $host_args -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$database_name'")"
  if [ "$exists" != "1" ]; then
    psql $host_args -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -c "CREATE DATABASE \"$database_name\""
  fi
}

create_database_if_missing crm_platform
create_database_if_missing crm_tenant
