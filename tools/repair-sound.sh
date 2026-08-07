#!/usr/bin/env bash
#
# repair-sound.sh -- diagnose, record, then repair the "audio sink goes dead"
# wedge on this machine.
#
# THE BUG
#
# Audio stops. Adjusting the volume does nothing, "Test sound" does nothing,
# and the only cure is switching sinks (headphones -> speakers -> headphones),
# after which everything the system tried to play comes out at once. Spotify
# keeps showing a running clock throughout.
#
# It is not the hardware. Captured mid-wedge on 2026-08-07, every ALSA PCM was
# `closed` and every sink node was healthy; the client stream had simply lost
# its link:
#
#     Sink Input #22221
#         Sink: 4294967295        <- PA_INVALID_INDEX: attached to NO sink
#         Corked: yes
#
# and the graph dump showed that stream's node with zero links to anything.
# So a stream got orphaned by the session manager and was never re-linked.
# Switching sinks fixes it because that forcibly re-attaches and uncorks,
# flushing whatever had buffered up -- the "all at once" you hear.
#
# `Corked: yes` on its own means nothing; a normally paused Spotify is corked
# too. `Sink: 4294967295` is the unambiguous signal, and it is what this
# script looks for.
#
# WHAT TRIGGERS IT
#
# Anything that destroys and recreates the sink nodes: Bluetooth headphones
# connecting or dropping, DP/HDMI sinks coming and going with monitor DPMS
# (three of the five sinks on this box are HDMI), card profile switches --
# and `systemctl --user restart wireplumber`, which is how it was reproduced
# by accident while debugging. The timer app was not running that time, which
# is why this script records whether it is running: so the next occurrence
# either implicates it or clears it, rather than leaving it a suspect.
#
# NOT the timer app's audio stream, at least as of 8dcde8b: it no longer holds
# a sink-input unless an alarm is within a second. If this script ever finds
# the app holding a stream while idle, that is a regression worth knowing.
#
# USAGE
#
#     tools/repair-sound.sh                 # record, then repair
#     tools/repair-sound.sh --observe-only  # record only, leave it broken
#
# Run it *while the sink is stuck*, before switching sinks by hand -- doing
# that first destroys the evidence.

set -uo pipefail

OBSERVE_ONLY=0
for arg in "$@"; do
	case "$arg" in
		--observe-only) OBSERVE_ONLY=1 ;;
		-h|--help) sed -n '3,60p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
		*) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
	esac
done

for tool in pactl pw-dump; do
	command -v "$tool" >/dev/null || { echo "missing required tool: $tool" >&2; exit 1; }
done

OUT="${TMPDIR:-/tmp}/audio-wedge-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
REPORT="$OUT/report.txt"

# Everything the script prints also lands in the report, so a /resume of the
# debugging session can read one file instead of reassembling scrollback.
exec > >(tee "$REPORT") 2>&1

echo "=== repair-sound.sh  $(date -Is) ==="
echo "recording to $OUT"
echo

# --- Is the timer app running? -------------------------------------------
#
# Recorded first and unconditionally, because the whole question about this
# app is whether it participates. `[n]aive_timer` keeps pgrep from matching
# its own command line.
echo "=== timer app ==="
APP_PIDS=$(pgrep -f '[n]aive_timer' 2>/dev/null | grep -vx "$$" | tr '\n' ' ')
APP_PIDS="${APP_PIDS% }"
if [ -n "$APP_PIDS" ]; then
	echo "RUNNING -- pids: $APP_PIDS"
	ps -o pid,lstart,etime,args -p "${APP_PIDS// /,}" 2>/dev/null | sed 's/^/  /'
else
	echo "NOT RUNNING"
fi
# Which build, so a later fix can be told apart from a later regression.
if git -C "$(dirname "$0")/.." rev-parse --short HEAD >/dev/null 2>&1; then
	echo "repo HEAD: $(git -C "$(dirname "$0")/.." rev-parse --short HEAD) \
($(git -C "$(dirname "$0")/.." rev-parse --abbrev-ref HEAD))"
fi
echo

# --- Sink-input inventory -------------------------------------------------
#
# Identifying *which* app is orphaned is the point, and it is not simply read
# off the stream. Spotify's sink-input carries no application.name and no
# application.process.id at all -- only `media.name = "audio-src"` and a
# `Client:` reference. The identifying properties live on the client object,
# so those are loaded first and joined in below. Qt's streams do carry
# application.name directly, hence the fallback chain rather than one source.
declare -A CLIENT_NAME CLIENT_PID
load_clients() {
	local idx="" val
	while IFS= read -r line; do
		case "$line" in
			"Client #"*)
				idx="${line#Client #}" ;;
			*"application.name = "*)
				val="${line#*= \"}"; CLIENT_NAME[$idx]="${val%\"}" ;;
			*"application.process.id = "*)
				val="${line#*= \"}"; CLIENT_PID[$idx]="${val%\"}" ;;
		esac
	done < <(pactl list clients 2>/dev/null)
}
load_clients

# Emits: index <TAB> sink <TAB> corked <TAB> pid <TAB> name
# for every stream, so the report shows healthy ones as context, not just the
# broken one.
inventory() {
	pactl list sink-inputs 2>/dev/null | awk '
		function flush() {
			if (idx != "") {
				if (name == "?" && media != "") name = media
				printf "%s\t%s\t%s\t%s\t%s\t%s\n", idx, sink, cork, pid, name, client
			}
			idx = ""; sink = "?"; cork = "?"; pid = "?"; name = "?"
			client = "?"; media = ""
		}
		/^Sink Input #/ { flush(); idx = substr($3, 2) }
		/^\tSink: /     { sink = $2 }
		/^\tCorked: /   { cork = $2 }
		/^\tClient: /   { client = $2 }
		/application\.process\.id = / { p = $0; gsub(/.*= "|"$/, "", p); pid = p }
		/application\.name = /        { n = $0; gsub(/.*= "|"$/, "", n); name = n }
		/media\.name = /              { m = $0; gsub(/.*= "|"$/, "", m); media = m }
		END { flush() }
	' | while IFS=$'\t' read -r idx sink cork pid name client; do
		# Fall back to the client object for whatever the stream omitted.
		[ "$pid"  = "?" ] && pid="${CLIENT_PID[$client]:-?}"
		[ "$name" = "?" ] && name="${CLIENT_NAME[$client]:-?}"
		# Prefer the client's app name over a generic stream name like
		# "audio-src", which identifies nothing.
		[ -n "${CLIENT_NAME[$client]:-}" ] && name="${CLIENT_NAME[$client]}"
		printf '%s\t%s\t%s\t%s\t%s\n' "$idx" "$sink" "$cork" "$pid" "$name"
	done
}

echo "=== sink-inputs ==="
printf "  %-7s %-12s %-7s %-8s %s\n" INDEX SINK CORKED PID NAME
inventory | while IFS=$'\t' read -r idx sink cork pid name; do
	mark="   "
	[ "$sink" = "4294967295" ] && mark="!! "
	printf "%s%-7s %-12s %-7s %-8s %s\n" "$mark" "$idx" "$sink" "$cork" "$pid" "$name"
done
echo "  (!! = orphaned: Sink 4294967295 is PA_INVALID_INDEX)"
echo

ORPHANS=$(inventory | awk -F'\t' '$2 == "4294967295" { print $1 }')

# Does the timer app hold a stream? Post-8dcde8b it should hold none unless an
# alarm is within ALERT_WARMUP_S, so a hit here is itself a finding.
if [ -n "$APP_PIDS" ]; then
	APP_STREAMS=$(inventory | awk -F'\t' -v pids=" $APP_PIDS " \
		'index(pids, " " $4 " ") { print $1 }' | tr '\n' ' ')
	if [ -n "$APP_STREAMS" ]; then
		echo "NOTE: the timer app holds sink-input(s): $APP_STREAMS"
		echo "      Expected only within ~1s of an alarm. Otherwise a regression."
	else
		echo "the timer app is running and holds no sink-input (expected)"
	fi
	echo
fi

# --- Everything else, for the record -------------------------------------
{
	echo "default-sink: $(pactl get-default-sink 2>/dev/null)"
	echo "pipewire: $(pipewire --version 2>&1 | tail -1)"
	echo "wireplumber: $(wireplumber --version 2>&1 | head -1)"
	echo "uptime: $(uptime)"
	echo
	# Daemon start times matter: pipewire up for weeks while wireplumber
	# restarted minutes ago means the session manager churned the nodes, which
	# is exactly the trigger class. This is how the 2026-08-07 instance was
	# traced back to a manual `systemctl --user restart wireplumber`.
	echo "audio daemon start times:"
	ps -o pid,lstart,etime,comm -p "$(pgrep -d, -x 'pipewire|wireplumber|pipewire-pulse')" 2>/dev/null
} > "$OUT/context.txt" 2>&1

pactl list        > "$OUT/pactl-list.txt"  2>&1
pw-dump           > "$OUT/pw-dump.json"    2>&1
command -v pw-cli >/dev/null && pw-cli info all > "$OUT/pw-cli-info.txt" 2>&1
cat /proc/asound/card*/pcm*p/sub*/status > "$OUT/alsa-pcm-status.txt" 2>&1

# Sink node IDs. PipeWire hands out monotonically increasing ids, so comparing
# these against an earlier capture shows whether the nodes were recreated --
# the cheap proxy for "device churn happened" without a running pw-mon.
python3 - "$OUT/pw-dump.json" > "$OUT/node-ids.txt" 2>&1 <<'PY'
import json, sys
try:
    objs = json.load(open(sys.argv[1]))
except Exception as exc:
    print("could not parse pw-dump:", exc); raise SystemExit
for o in objs:
    if not o.get("type", "").endswith("Node"):
        continue
    info = o.get("info", {}) or {}
    props = info.get("props", {}) or {}
    cls = props.get("media.class", "")
    if cls in ("Audio/Sink", "Stream/Output/Audio"):
        print(f'{o["id"]:6}  {info.get("state","?"):10} {cls:20} '
              f'{props.get("node.name") or props.get("application.name")}')
PY

# Correlating events. The cause is in the seconds *before* the wedge, so these
# windows are what actually name a trigger once a few captures accumulate.
journalctl -k -b --no-pager --since "-30 min" 2>/dev/null \
	| grep -iE "bluetooth|drm|i915|hdmi|sof|sdw|snd_|xrun" > "$OUT/kernel.txt" 2>&1
journalctl --user --no-pager --since "-30 min" \
	-u pipewire -u pipewire-pulse -u wireplumber   > "$OUT/services.txt" 2>&1
journalctl --no-pager --since "-30 min" 2>/dev/null \
	-u bluetooth -u systemd-logind                 > "$OUT/system-events.txt" 2>&1

# --- Repair ---------------------------------------------------------------
echo "=== repair ==="
if [ -z "$ORPHANS" ]; then
	echo "no orphaned streams found."
	echo "If audio is dead anyway, this is a DIFFERENT failure than the one"
	echo "this script knows about -- keep $OUT and say so; that is new data."
	exit 0
fi

if [ "$OBSERVE_ONLY" = "1" ]; then
	echo "--observe-only: leaving $(echo "$ORPHANS" | wc -l) orphaned stream(s) alone."
	echo "repair by hand with: pactl move-sink-input <index> \$(pactl get-default-sink)"
	exit 0
fi

DEFAULT_SINK=$(pactl get-default-sink)
for idx in $ORPHANS; do
	echo -n "  moving sink-input $idx -> $DEFAULT_SINK ... "
	if pactl move-sink-input "$idx" "$DEFAULT_SINK" 2>/dev/null; then
		echo "ok"
	else
		echo "FAILED"
	fi
done

sleep 1
STILL=$(inventory | awk -F'\t' '$2 == "4294967295" { print $1 }')

# Fallback: bounce the default sink. This is the by-hand cure (switch to
# speakers and back), and it re-links every stream rather than one, so it is
# worth trying when a targeted move did not take. Louder than the move -- it
# briefly relocates *all* audio -- hence second, not first.
if [ -n "$STILL" ]; then
	OTHER=$(pactl list short sinks | awk -v d="$DEFAULT_SINK" '$2 != d { print $2; exit }')
	if [ -n "$OTHER" ]; then
		echo "  still orphaned; bouncing the default sink via $OTHER"
		pactl set-default-sink "$OTHER"; sleep 1
		pactl set-default-sink "$DEFAULT_SINK"; sleep 1
		STILL=$(inventory | awk -F'\t' '$2 == "4294967295" { print $1 }')
	else
		echo "  still orphaned, and no second sink to bounce through"
	fi
fi

echo
if [ -n "$STILL" ]; then
	echo "RESULT: still orphaned -- $STILL"
	echo "Switch sinks in the GUI and note whether that works; if it does,"
	echo "this script's repair is incomplete and that is worth recording."
else
	echo "RESULT: repaired. All streams have a sink again."
	echo "Play something to confirm it is actually audible."
fi
echo
echo "capture saved to $OUT"
