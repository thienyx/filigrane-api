#!/bin/sh
set -eu

if [ "${SKIP_DB_MIGRATIONS:-}" = "1" ] || [ "${SKIP_DB_MIGRATIONS:-}" = "true" ]; then
  echo "docker-entrypoint: SKIP_DB_MIGRATIONS set, skipping alembic upgrade"
else
  echo "docker-entrypoint: alembic upgrade head"
  alembic upgrade head
fi

exec "$@"
