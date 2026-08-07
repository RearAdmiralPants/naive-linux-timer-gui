#!/usr/bin/env bash
# Snapshot the audio graph the moment the sink goes dead.
#
# The wedge is intermittent, so the next occurrence is the only chance to get
# real data. Run this *while the sink is stuck* -- before switching sinks to
# unstick it, because switching destroys the evidence.
#
#   tools/capture-audio-wedge.sh
#
# Then unstick it however you normally do, and run it once more with `after`
# as an argument to get a healthy baseline to diff against:
#
#   tools/capture-audio-wedge.sh after

set -uo pipefail

tag="${1:-wedged}"
out="${TMPDIR:-/tmp}/audio-wedge-$(date +%Y%m%d-%H%M%S)-${tag}"
mkdir -p "$out"

echo "capturing to $out"

# The two that matter most: node states (is the sink RUNNING but not draining?)
# and whether each client thinks it is streaming.
pw-dump                 > "$out/pw-dump.json"      2>&1
pactl list              > "$out/pactl-list.txt"    2>&1
pw-cli info all         > "$out/pw-cli-info.txt"   2>&1
pw-top -b -n 4          > "$out/pw-top.txt"        2>&1

# Driver-side: has the ALSA device actually stopped, and did the DSP complain?
journalctl -k -b --no-pager --since "-30 min" \
  | grep -iE "sof|soundwire|sdw|snd_|xrun|underrun|ipc" > "$out/kernel.txt" 2>&1
journalctl --user -u pipewire -u pipewire-pulse -u wireplumber \
  --no-pager --since "-30 min"                            > "$out/services.txt" 2>&1

cat /proc/asound/card*/pcm*p/sub*/status > "$out/alsa-pcm-status.txt" 2>&1

{
  echo "default-sink: $(pactl get-default-sink)"
  echo "pipewire: $(pipewire --version | tail -1)"
  echo "uptime: $(uptime)"
  pgrep -a -f 'naive_timer|spotify --type=renderer' | head
} > "$out/context.txt" 2>&1

echo
echo "sink states right now:"
pactl list sinks | grep -E "Name:|State:"
echo
echo "sink-inputs right now:"
pactl list sink-inputs | grep -E "^Sink Input|application.name |Corked:|Sample Specification"
echo
echo "done -> $out"
