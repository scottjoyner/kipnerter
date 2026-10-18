#!/usr/bin/env bash
# Install a local-only observer without adding Tailscale Serve/Funnel routes.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REAL_HOME="$(python3 -c 'import os,pwd; print(pwd.getpwuid(os.getuid()).pw_dir)')"
DEST="$REAL_HOME/.local/share/kipnerter-observer"
CONF="$REAL_HOME/.config/kipnerter-observer"
UNIT_DIR="$REAL_HOME/.config/systemd/user"
SERVICE=kipnerter-observer.service
if [[ "${1:-}" != "--install" ]]; then
  printf 'Plan only: copy pinned observer code into %s, install user systemd service, generate a local-only token.\n' "$DEST"
  printf 'Requires --install. No Tailscale Serve config or production secrets are touched.\n'
  exit 0
fi
command -v systemctl >/dev/null
command -v tailscale >/dev/null
[[ ! -e "$DEST/app" || ! -L "$DEST/app" ]] || { echo "symlinked install directory denied"; exit 1; }
umask 077
mkdir -p "$DEST/app" "$CONF" "$UNIT_DIR"
install -m 0600 "$ROOT/apps/api/app/agent_sessions_observer.py" "$DEST/app/"
install -m 0600 "$ROOT/apps/api/app/tailnet_observer.py" "$DEST/app/"
install -m 0600 "$ROOT/apps/api/app/trace_snapshot_observer.py" "$DEST/app/"
install -m 0600 "$ROOT/apps/api/app/assistx_fleet_observer.py" "$DEST/app/"
install -m 0700 "$ROOT/scripts/refresh_assistx_fleet_snapshot.py" "$DEST/"
install -m 0700 "$ROOT/scripts/refresh_assistx_trace_snapshot.py" "$DEST/"
[[ ! -L "$DEST/app/__init__.py" ]] || { echo "symlinked package initializer denied"; exit 1; }
touch "$DEST/app/__init__.py"
chmod 0600 "$DEST/app/__init__.py"
if [[ ! -e "$CONF/observer.env" ]]; then
  python3 - "$CONF/observer.env" <<'PY'
import pathlib, secrets, sys
path=pathlib.Path(sys.argv[1])
with path.open("x") as stream:
    stream.write("FLEET_MONITOR_TOKEN=" + secrets.token_urlsafe(48) + "\n")
    stream.write("FLEET_MONITOR_BIND=127.0.0.1\nFLEET_MONITOR_PORT=8769\n")
path.chmod(0o600)
PY
else
  [[ ! -L "$CONF/observer.env" ]] || { echo "symlinked secret file denied"; exit 1; }
fi
install -m 0644 "$ROOT/infra/systemd/$SERVICE" "$UNIT_DIR/$SERVICE"
install -m 0644 "$ROOT/infra/systemd/kipnerter-trace-publisher.service" "$UNIT_DIR/"
install -m 0644 "$ROOT/infra/systemd/kipnerter-trace-publisher.timer" "$UNIT_DIR/"
install -m 0644 "$ROOT/infra/systemd/kipnerter-fleet-publisher.service" "$UNIT_DIR/"
install -m 0644 "$ROOT/infra/systemd/kipnerter-fleet-publisher.timer" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE"
# One-shot snapshot publisher runs separately and is NEVER callable over HTTP.
# This unit uses the existing local AssistX container's current auth and emits
# only allowlisted metadata; no privileged credentials leave that container.
systemctl --user enable --now kipnerter-trace-publisher.timer
systemctl --user start kipnerter-trace-publisher.service
systemctl --user enable --now kipnerter-fleet-publisher.timer
systemctl --user start kipnerter-fleet-publisher.service
systemctl --user restart "$SERVICE"
active=0
for attempt in {1..15}; do
  if systemctl --user is-active --quiet "$SERVICE" &&       [[ "$(curl -sS --max-time 1 -o /dev/null -w '%{http_code}' http://127.0.0.1:8769/v1/nodes 2>/dev/null)" == 401 ]]; then
    active=1
    break
  fi
  sleep 1
done
if (( active != 1 )); then
  echo "Observer failed to start securely; check systemctl --user status $SERVICE" >&2
  exit 1
fi
echo "Verified: observer bound to loopback, unauthenticated request denied (401); Serve/Funnel unchanged."
