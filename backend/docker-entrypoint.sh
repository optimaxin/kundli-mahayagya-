#!/bin/sh
# Optional start-up tasks, controlled by environment variables:
#   RUN_MIGRATIONS=true  -> alembic upgrade head before starting
#   RUN_SEED=true        -> idempotent seed of sessions / Kunds / capacity
# In production prefer running migrations as a separate one-off job.
set -e

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "Running database migrations..."
  alembic upgrade head
fi

if [ "${RUN_SEED:-false}" = "true" ]; then
  echo "Seeding sessions, Kunds and capacity..."
  python -m scripts.seed_all
fi

exec "$@"
