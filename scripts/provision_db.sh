#!/usr/bin/env bash
# One-time PostgreSQL provisioning for Urban Sentinel: creates an application role and database.
#
# Usage:
#   export PGPASSWORD="<postgres-superuser-password>"
#   ./scripts/provision_db.sh [database] [user] <app-password>
#
# Idempotent: existing roles/databases are left alone. Never prints any password.
set -euo pipefail

DB="${1:-urban_sentinel}"
APP_USER="${2:-urban_sentinel}"
APP_PASSWORD="${3:?app password required as third argument}"
PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
SUPERUSER="${PGSUPERUSER:-postgres}"

: "${PGPASSWORD:?set PGPASSWORD to the PostgreSQL superuser password}"

for name in "$DB" "$APP_USER"; do
  [[ "$name" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid identifier: $name" >&2; exit 1; }
done

PSQL=(psql -h "$PGHOST" -p "$PGPORT" -U "$SUPERUSER" -v ON_ERROR_STOP=1 -q -t -A)
ESCAPED_PASSWORD="${APP_PASSWORD//\'/\'\'}"

if [[ "$("${PSQL[@]}" -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname = '$APP_USER'")" != "1" ]]; then
  echo "CREATE ROLE $APP_USER LOGIN PASSWORD '$ESCAPED_PASSWORD';" | "${PSQL[@]}" -d postgres >/dev/null
  echo "Created role $APP_USER"
else
  echo "Role $APP_USER already exists (password unchanged)"
fi

if [[ "$("${PSQL[@]}" -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$DB'")" != "1" ]]; then
  "${PSQL[@]}" -d postgres -c "CREATE DATABASE $DB OWNER $APP_USER" >/dev/null
  echo "Created database $DB"
else
  echo "Database $DB already exists"
fi

"${PSQL[@]}" -d "$DB" -c "GRANT CREATE ON SCHEMA public TO $APP_USER" >/dev/null
echo "Done. Next: export DATABASE_URL and run 'alembic upgrade head'."
