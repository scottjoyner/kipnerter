#!/usr/bin/env bash
set -euo pipefail

: "${ROLLBACK_SHA:?Set ROLLBACK_SHA to a previously validated commit}"

ROOT=${KIPNERTER_ROOT:-/opt/kipnerter}
cd "$ROOT"

git fetch origin --prune
if ! git cat-file -e "${ROLLBACK_SHA}^{commit}" 2>/dev/null; then
  echo "Unknown rollback commit: $ROLLBACK_SHA" >&2
  exit 2
fi

CURRENT_SHA=$(git rev-parse HEAD)
echo "Rolling back from $CURRENT_SHA to $ROLLBACK_SHA"
git checkout --detach "$ROLLBACK_SHA"
docker compose --profile edge build
docker compose --profile edge up -d --remove-orphans

for attempt in {1..20}; do
  if curl --fail --silent http://127.0.0.1:8000/health >/dev/null 2>&1 || docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"; then
    echo "Rollback healthy at $ROLLBACK_SHA"
    exit 0
  fi
  sleep 3
done

echo "Rollback deployment failed health validation." >&2
exit 1
