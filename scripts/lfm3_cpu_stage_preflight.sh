#!/usr/bin/env bash
# READ-ONLY feasibility gate for a separate local CPU model on the production host.
# Does not read, create or copy any production/fleet credentials.
set -euo pipefail

hold() { printf 'CPU_STAGE_HOLD: %s\n' "$1" >&2; exit 3; }
[[ "$(id -un)" == "kipnerter" ]] || hold "incorrect host principal"
[[ "$(uname -m)" == "x86_64" ]] || hold "pinned Linux CPU runtime requires x86_64"
for cmd in docker python3 df; do
  command -v "$cmd" >/dev/null 2>&1 || hold "missing required host command"
done
docker compose version >/dev/null 2>&1 || hold "Docker Compose unavailable"
docker info --format '{{.ServerVersion}}' >/dev/null 2>&1 || hold "Docker engine unavailable"

# Isolated staging must never replace an existing container or occupy a live port.
for name in kipnerter-lfm3-stage-cpu-web kipnerter-lfm3-stage-cpu-model; do
  if docker container inspect "$name" >/dev/null 2>&1; then
    hold "CPU stage container name already exists"
  fi
done

python3 - <<'PY'
import os, socket, shutil, sys
def hold(reason):
    print("CPU_STAGE_HOLD: " + reason, file=sys.stderr)
    raise SystemExit(3)
try:
    available_kib = next(int(row.split()[1]) for row in open("/proc/meminfo")
                         if row.startswith("MemAvailable:"))
    disk_bytes = shutil.disk_usage("/").free
    cpus = len(os.sched_getaffinity(0))
except (OSError, ValueError, StopIteration):
    hold("host resources cannot be measured")
print(f"CPU_STAGE_RESOURCES: available_ram_kib={available_kib} free_disk_bytes={disk_bytes} available_cpus={cpus}")
if available_kib < 6 * 1024 * 1024:
    hold("less than 6 GiB available RAM; do not evict other workloads")
if disk_bytes < 10 * 1024 ** 3:
    hold("less than 10 GiB free disk; do not stage model and images")
if cpus < 2:
    hold("fewer than two schedulable CPUs")
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    try:
        s.bind(("127.0.0.1", 3363))
    except OSError:
        hold("loopback staging port 3363 is occupied")
PY
printf '%s\n' 'CPU_STAGE_READINESS_PASS: resource/identity/port checks only; writes=none; RX480 credential untouched'
