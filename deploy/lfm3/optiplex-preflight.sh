#!/usr/bin/env bash
set -euo pipefail
model=/home/scott/lfm3-research/gguf/LFM3-1.7B-Q4_K_M.gguf
key=/home/scott/.config/kipnerter/lfm3-optiplex.key
test -s "$model" && test -s "$key"
test "$(stat -c %a "$key")" = 600
test "$(tailscale ip -4 | head -1)" = 100.69.158.114
test "$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)" -ge 3500000
echo 'OptiPlex LFM3 low-priority CPU preflight PASS'
