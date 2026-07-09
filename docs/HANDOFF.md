# Handoff notes

Context for picking this project back up — especially in a **fresh Claude Code
session** (e.g. the local CLI), since a Claude Code conversation's memory does
not transfer between the web/mobile app and a local terminal session. The code
travels via git; this document travels the *reasoning* that isn't obvious from
the diff.

_Last updated: 2026-07-09, after the first run on real hardware._

## Lesson from the first local run

The cloud session shipped 38 green tests and an app that **aborted before
drawing a pixel**: `_AlertPlayer` passed `QSoundEffect.Infinite` (an enum) to
`setLoopCount`, which under PySide6 6.11 wants an `int`. Compile-checking
`app.py` could never have caught it, and no model test touches Qt.

The fix is one line. The lesson is the important part: **"the logic is
headlessly testable" is not the same as "the app starts."** `tests/
test_gui_smoke.py` now constructs `MainWindow` and `_AlertPlayer` under
`QT_QPA_PLATFORM=offscreen` — no display needed, so it runs in the same cloud
container that missed the bug. It fails on the pre-fix code; that was verified,
not assumed.

Separately, PySide6 wheels don't bundle `libxcb-cursor0`, which Qt 6.5+ needs
for the `xcb` platform plugin. It's a `sudo apt install`, now in the README.

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
| `src/naive_timer/app.py` | PySide6 tabbed GUI + animated spinner | ⚠️ constructed offscreen only |

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

Answered at the first local run:

- [x] **Visual alert**: the red flash is **too busy / jarring**. Superseded by
  the shard treatment below — on finish the shard breaks apart and pulses to a
  mostly-transparent dark red at ~1–2 Hz until reset.
- [x] **Spinner**: the orbiting-dots ring is distracting and is being
  **removed**, not kept alongside the 3D view.

Still open:

- [ ] **Chime**: still unheard (DSP was muted during the first run). Volume
  0.35, ~1.5 s clip, infinite loop.
- [ ] **Minutes-vs-seconds** default for bare numbers (see choice #1).
- [ ] Whether to surface **config** (sound file, alert duration) in the UI.

## Next: the 3D shard

Replacing the spinner. The timer/stopwatch text becomes a **dynamic texture on
the face of an angled glass shard**, lit from offscreen.

- Route: `QOpenGLWidget` + hand-written GLSL (all of QtQuick3D / Qt3D /
  QtWebEngine are installed via PySide6-Addons, but raw GL is the least fight
  for custom lighting). Confirmed OpenGL 4.6 core on Mesa.
- Text → `QPainter` into a `QImage` → `QOpenGLTexture` → sampled by the
  fragment shader. **`format_elapsed` is the seam**: the models stay UI-free
  and headlessly testable, and the GL widget is just another thin view.
- Wanted knobs: **font face**, **numeral color**, and an optional **emissive
  glow** vs. an etched/frosted look (undecided — needs to be seen).
- On finish: shard fractures, then pulses transparent dark red at ~1–2 Hz until
  the user resets or starts another timer.

## Running locally

```bash
sudo apt install libxcb-cursor0            # Qt 6.5+ xcb plugin dep; not in the wheel
python3 -m venv .venv                      # system Python is externally managed
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m unittest discover -s tests -v   # logic + offscreen GUI smoke
.venv/bin/python -m naive_timer                     # see/hear the GUI
```

## Branch

Work is on `claude/mobile-code-git-workflow-aptdpv`. No PR has been opened yet.
