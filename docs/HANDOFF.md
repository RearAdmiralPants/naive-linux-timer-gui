# Handoff notes

Context for picking this project back up — especially in a **fresh Claude Code
session** (e.g. the local CLI), since a Claude Code conversation's memory does
not transfer between the web/mobile app and a local terminal session. The code
travels via git; this document travels the *reasoning* that isn't obvious from
the diff.

_Last updated: 2026-07-09, after adding the countdown/alarm Timer mode._

## Where things stand

Two features, both working:

- **Stopwatch** — start/pause/resume/reset, lap support in the model,
  `HH:MM:SS.cs` readout.
- **Timer (countdown / alarm)** — Duration mode (`12m`, `1h30m`, `90s`,
  `25:00`) and Alarm-at mode (`02:54`, `6:30pm`, rolls to tomorrow if past).
  On zero: visual flash + a gentle chime looping ~2 min or until Dismiss.

38 unit tests, all passing headlessly (`python -m unittest discover -s tests`).

## Architecture (and why)

The guiding constraint has been **remote iteration**: much of this was built
from the mobile app in a cloud container with no display. So:

> **All timekeeping/parsing/sound logic is UI-free and dependency-free, and
> lives separately from the Qt view.**

That's what lets the logic be fully unit-tested without a screen. The Qt layer
(`app.py`) is deliberately thin — it renders model state and forwards button
presses, nothing more.

| File | Role | Tested headlessly? |
|------|------|--------------------|
| `src/naive_timer/stopwatch.py` | Stopwatch model + `format_elapsed` | ✅ |
| `src/naive_timer/countdown.py` | Countdown model + `parse_duration`/`parse_alarm` | ✅ |
| `src/naive_timer/sound.py` | Runtime chime WAV synthesis (stdlib `wave`) | ✅ |
| `src/naive_timer/app.py` | PySide6 tabbed GUI + animated spinner | ⚠️ compile-checked only |

Key model details worth knowing before editing:

- **Injectable clock.** Both models take a `clock` callable (default
  `time.monotonic`) so tests advance time with a fake clock instead of sleeping.
- **Alert window is measured from the true zero-crossing**, not from when the
  UI polls. `Countdown._check_finish` records `_finished_at` as the exact
  instant elapsed crossed `total`, so a late first observation doesn't extend
  the alert. There's a test pinning this (`test_alert_measured_from_zero_...`).
- **Sound is generated, not committed.** No binary asset in the repo;
  `sound.generate_chime_wav` synthesizes a soft D5→A5 chime. Swap the `notes`
  or point `_AlertPlayer` at your own WAV to customize.
- **Audio degrades gracefully.** If `PySide6.QtMultimedia` isn't present, the
  alert is visual-only (`_HAVE_AUDIO` guard in `app.py`).

## Deliberate design choices (may want revisiting in person)

1. **Bare number in Duration mode = minutes.** `12` → 12 minutes (kitchen-timer
   convention). Could instead mean seconds, or we could auto-detect.
2. **Duration vs. Alarm is an explicit dropdown**, not auto-detected from the
   text — because `12:00` is ambiguous (12 min 0 sec vs. 12:00 clock time).
3. **Alert = red flash + looping chime for 120 s.** The duration is a parameter
   (`Countdown.alert_duration`); the flash aggressiveness and chime character
   are hardcoded in `app.py` for now.

## Open questions (waiting on in-person / on-workstation review)

These are the "needs your eyes/ears" items that couldn't be judged remotely:

- [ ] **Chime**: right volume? too frequent? pleasant enough? (currently
  volume 0.35, ~1.5 s clip on infinite loop)
- [ ] **Visual alert**: is a red background flash the right level of
  aggressiveness, or too much / not enough?
- [ ] **Minutes-vs-seconds** default for bare numbers (see choice #1).
- [ ] Whether to add a **countdown-specific config** (default sound file,
  default alert duration) surfaced in the UI rather than just in code.

## Running locally

```bash
git checkout claude/mobile-code-git-workflow-aptdpv
git pull
pip install PySide6
python -m unittest discover -s tests -v   # verify logic
python -m naive_timer                      # see/hear the GUI
```

## Branch

Work is on `claude/mobile-code-git-workflow-aptdpv`. No PR has been opened yet.
