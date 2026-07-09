# naive-linux-timer-gui

A simple stopwatch/timer running in Linux with naive 3D/animation features.

Built with [PySide6](https://doc.qt.io/qtforpython/) (Qt for Python). The
timekeeping logic is kept UI-free and fully unit-tested, so it can be developed
and verified without a display; the Qt layer is a thin view on top.

## Features

**Stopwatch tab**
- Start / pause / resume / reset stopwatch
- `HH:MM:SS.cs` readout at ~60 FPS
- Lap support in the core model

**Timer tab (countdown / alarm)**
- **Duration** mode: count down a timespan — `12m`, `1h30m`, `90s`, or `25:00`
- **Alarm at** mode: count down to a clock time — `02:54`, `14:00`, `6:30pm`
  (rolls to tomorrow if the time has already passed today)
- On reaching zero: a visual flash plus a gentle chime that loops quietly for
  ~2 minutes (configurable) or until you hit **Dismiss**
- The chime is synthesized at runtime (no binary asset); point it at your own
  WAV to customize

Both tabs share a naive animated pseudo-3D spinner (rotating gradient ring with
orbiting dots) that reacts to running/alarm state — a starting point for
fancier effects.

## Prerequisites

Qt 6.5+ needs a system library that the PySide6 wheels do **not** bundle.
Without it the app aborts at startup with `Could not load the Qt platform
plugin "xcb"`. On Debian / Ubuntu / Mint:

```bash
sudo apt install libxcb-cursor0
```

This is the only thing that belongs to `sudo`. Everything Python-side goes in a
virtualenv (below) — on Mint and other distros with an *externally managed*
system Python, `sudo pip install` is both blocked and a good way to break
`apt`-managed tooling.

## Run it

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m naive_timer
```

To install it as a real command (`naive-timer`) without touching the system
Python, use [pipx](https://pipx.pypa.io/) — it builds a private virtualenv per
application and puts the entry point on your `PATH`:

```bash
pipx install .
naive-timer
```

## Develop / test

The stopwatch, countdown, and sound models have no GUI dependency and can be
tested anywhere, with no third-party packages:

```bash
python -m unittest discover -s tests -v
```

`tests/test_gui_smoke.py` additionally constructs the Qt widgets under
`QT_QPA_PLATFORM=offscreen`. It needs PySide6 installed but **no display**, so
it runs in CI and cloud containers; it skips itself if PySide6 is absent. It
exists because the model tests can be entirely green while the app crashes on
startup — which is exactly what happened once.

```bash
.venv/bin/python -m unittest discover -s tests -v   # includes the GUI smoke test
.venv/bin/python -m pytest                          # same, via pytest
```

## Layout

```
src/naive_timer/
  stopwatch.py   # pure stopwatch model (no Qt) — unit-tested
  countdown.py   # pure countdown model + duration/alarm parsing — unit-tested
  sound.py       # runtime chime WAV synthesis (stdlib only) — unit-tested
  app.py         # PySide6 tabbed window + animated spinner (thin view)
  __main__.py    # enables `python -m naive_timer`
tests/
  test_stopwatch.py
  test_countdown.py
  test_sound.py
  test_gui_smoke.py  # constructs the Qt widgets offscreen (needs PySide6)
```

The separation is deliberate: logic changes can be verified headlessly (e.g. in
a cloud/CI session), while the visual layer is reviewed by running it locally.
