#!/usr/bin/env bash
set -euo pipefail
model=/home/scott/lfm3-research/gguf/LFM3-1.7B-QAD-Q4_0.gguf
key=/home/scott/.config/kipnerter/lfm3-rx480.key
test -s "$model" && test -s "$key"
test "$(stat -c %a "$key")" = 600
test "$(tailscale ip -4 | head -1)" = 100.78.106.121
vram=/sys/class/drm/card1/device
total=$(cat "$vram/mem_info_vram_total")
used=$(cat "$vram/mem_info_vram_used")
test $((total-used)) -ge 2400000000
test "$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)" -ge 6000000
echo 'RX480 LFM3 admission preflight PASS: model, key, tailnet, host RAM, and GPU VRAM'
