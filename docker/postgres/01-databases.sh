#!/bin/bash
# First start of an empty Postgres data directory only.
# The image has already created the role in POSTGRES_USER and the database in
# POSTGRES_DB (newsroom). This adds the other databases the app and pytest expect.
# Later container starts skip /docker-entrypoint-initdb.d. Schema is applied by
# the compose migrate service, not by this script.

set -euo pipefail

databases=(
  newsroom_test
  newsroom_analytics
  newsroom_analytics_test
)

for name in "${databases[@]}"; do
  echo "ensuring database ${name}"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v name="$name" -v owner="$POSTGRES_USER" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'name', :'owner')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'name')
\gexec
SQL
done
