#!/usr/bin/env python3
"""Go / pause / stop gate for long agentic runs, built on `claude-usage --json`.

The five-hour rule is about *pace*, not level. An even burn reaches 100% exactly
at reset, so "on pace" at elapsed fraction e means utilization == 100*e. Being
`ahead` points over that line and continuing at the even rate means you run out
ahead/100 of a window early, so for a 5 h window:

    projected lockout (min) = ahead * 3

Pausing fixes it: waiting lets the line catch up with usage. The gate pauses
when the projected lockout exceeds --max-lockout and says how long to wait.

The weekly rule is a hard ceiling (--weekly-cap) that needs a human to lift.

Exit codes: 0 go, 2 pause (wait, then re-check), 3 hard stop, 1 error.
The usage endpoint rate-limits, so results are cached for --ttl seconds and
callers can check as often as they like.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

FIVE_H = 5 * 3600
CACHE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "usage_gate.json"


def fetch(ttl: float) -> dict:
    try:
        if time.time() - CACHE.stat().st_mtime < ttl:
            return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        pass
    out = subprocess.run(["claude-usage", "--json"], capture_output=True,
                         text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "claude-usage failed")
    data = json.loads(out.stdout)
    CACHE.write_text(json.dumps(data))
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weekly-cap", type=float, default=33.0)
    ap.add_argument("--max-lockout", type=float, default=30.0,
                    help="minutes of projected 5h lockout to tolerate")
    ap.add_argument("--ttl", type=float, default=90.0)
    args = ap.parse_args()

    try:
        data = fetch(args.ttl)
    except Exception as exc:  # noqa: BLE001 -- any failure means "can't tell"
        print(f"ERROR {exc}")
        return 1

    week = float(data["seven_day"]["utilization"] or 0)
    five = data["five_hour"]
    used = float(five["utilization"] or 0)
    now = datetime.now(timezone.utc)
    resets = five.get("resets_at")
    if resets:
        remaining = (datetime.fromisoformat(resets) - now).total_seconds()
    else:
        remaining = FIVE_H
    if remaining <= 0:  # reset already passed: the next window starts fresh
        remaining = FIVE_H
    remaining = min(FIVE_H, remaining)
    expected = (FIVE_H - remaining) / FIVE_H * 100
    ahead = used - expected
    lockout_min = max(0.0, ahead) * FIVE_H / 6000
    line = (f"5h {used:.0f}% (pace {expected:.0f}%, ahead {ahead:+.0f}, "
            f"lockout~{lockout_min:.0f}m, resets {remaining / 60:.0f}m) | "
            f"week {week:.0f}%/{args.weekly_cap:.0f}%")

    if week >= args.weekly_cap:
        print(f"STOP {line}")
        return 3
    if lockout_min > args.max_lockout:
        # Wait until the projected lockout is back inside the allowance.
        excess_pts = ahead - args.max_lockout * 6000 / FIVE_H
        wait_s = max(60.0, min(remaining, excess_pts / 100 * FIVE_H))
        print(f"PAUSE {wait_s:.0f}s {line}")
        return 2
    print(f"GO {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
