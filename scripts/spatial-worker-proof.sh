#!/bin/sh
set -eu

RESULT_JSON="${1:-/tmp/kipnerter-spatial-smoke.json}"
COMPOSE_ARGS="-f docker-compose.yml -f compose.spatial.yml"

if [ ! -f "$RESULT_JSON" ]; then
  echo "Missing smoke result: $RESULT_JSON" >&2
  exit 2
fi

SCAN_ID="$(python3 - "$RESULT_JSON" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    print(json.load(f)['scan_id'])
PY
)"
ARTIFACT_ID="$(python3 - "$RESULT_JSON" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    print(json.load(f)['artifact_id'])
PY
)"

case "$SCAN_ID" in
  *[!0-9a-fA-F-]*|'') echo "Invalid scan id" >&2; exit 2 ;;
esac
case "$ARTIFACT_ID" in
  *[!0-9a-fA-F-]*|'') echo "Invalid artifact id" >&2; exit 2 ;;
esac

attempt=1
while [ "$attempt" -le 30 ]; do
  ROW="$(docker compose $COMPOSE_ARGS exec -T spatial-postgres \
    psql -U kipnerter -d kipnerter -At -F '|' \
    -c "SELECT status, processor, processor_version, room_count, COALESCE(error, '') FROM processing_reports WHERE scan_id = '$SCAN_ID'::uuid AND artifact_id = '$ARTIFACT_ID'::uuid ORDER BY created_at DESC LIMIT 1;" 2>/dev/null || true)"

  if [ -n "$ROW" ]; then
    STATUS="$(printf '%s' "$ROW" | cut -d'|' -f1)"
    echo "Processing report: $ROW"
    case "$STATUS" in
      complete|completed)
        UNPUBLISHED="$(docker compose $COMPOSE_ARGS exec -T spatial-postgres \
          psql -U kipnerter -d kipnerter -At \
          -c "SELECT count(*) FROM outbox_events WHERE aggregate_id = '$SCAN_ID'::uuid AND event_type = 'scan.completed' AND published_at IS NULL;" 2>/dev/null || printf 'unknown')"
        if [ "$UNPUBLISHED" != "0" ]; then
          echo "scan.completed still unpublished for $SCAN_ID: $UNPUBLISHED" >&2
          exit 1
        fi
        echo "PASS RoomPlan worker completed scan=$SCAN_ID artifact=$ARTIFACT_ID and published its outbox event"
        exit 0
        ;;
      failed)
        echo "RoomPlan processing failed for $SCAN_ID" >&2
        exit 1
        ;;
    esac
  fi

  sleep 2
  attempt=$((attempt + 1))
done

echo "Timed out waiting for complete RoomPlan processing report for scan=$SCAN_ID artifact=$ARTIFACT_ID" >&2
docker compose $COMPOSE_ARGS logs --tail=100 spatial-worker >&2 || true
exit 1
