#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

command -v docker >/dev/null || {
  echo "Docker is required." >&2
  exit 1
}

command -v uv >/dev/null || {
  echo "uv is required." >&2
  exit 1
}

docker info >/dev/null

# Include offline HTML/PDF checks when explicitly requested.
UV_ARGS=(--locked)
if [[ "${1:-}" == "--with-ingestion" ]]; then
  UV_ARGS+=(--extra ingestion)
  shift
fi

# Install the locked project and development dependencies.
uv sync "${UV_ARGS[@]}" --dev

TEST_CONTAINER_ID=""

cleanup() {
  if [[ -n "$TEST_CONTAINER_ID" ]]; then
    docker rm --force --volumes "$TEST_CONTAINER_ID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Docker chooses an available host port.
# No application database or existing volume is used.
TEST_CONTAINER_ID="$(
  docker run --detach \
    --publish 127.0.0.1::5432 \
    --env POSTGRES_USER=investigator \
    --env POSTGRES_PASSWORD=test-only \
    --env POSTGRES_DB=investigator_test \
    --health-cmd='pg_isready -U investigator -d investigator_test' \
    --health-interval=1s \
    --health-timeout=3s \
    --health-retries=30 \
    postgres:17-alpine
)"

echo "Waiting for PostgreSQL..."

POSTGRES_READY=false

for ((attempt = 1; attempt <= 60; attempt++)); do
  HEALTH_STATUS="$(
    docker inspect --format '{{.State.Health.Status}}' "$TEST_CONTAINER_ID"
  )"

  case "$HEALTH_STATUS" in
    healthy)
      POSTGRES_READY=true
      break
      ;;
    unhealthy)
      break
      ;;
  esac

  sleep 1
done

if [[ "$POSTGRES_READY" != true ]]; then
  echo "PostgreSQL did not become ready." >&2
  docker logs "$TEST_CONTAINER_ID" >&2
  exit 1
fi

TEST_DB_PORT="$(
  docker inspect \
    --format '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}' \
    "$TEST_CONTAINER_ID"
)"

export TEST_DATABASE_URL="postgresql+psycopg://investigator:test-only@127.0.0.1:${TEST_DB_PORT}/investigator_test"
export LLM_ENABLED=false

# With no arguments, run the complete suite.
# Otherwise, forward arguments to pytest.
if [[ "$#" -eq 0 ]]; then
  set -- -q
fi

uv run "${UV_ARGS[@]}" pytest "$@"