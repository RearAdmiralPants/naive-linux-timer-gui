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

## Run it

On your Linux workstation:

```bash
# from a virtualenv or your user environment
pip install PySide6
python -m naive_timer
```

Or install the package (adds a `naive-timer` command):

```bash
pip install -e .
naive-timer
```

## Develop / test

The stopwatch model has no GUI dependency and can be tested anywhere:

```bash
# stdlib only, no extra deps needed
python -m unittest discover -s tests -v

# or, if you have pytest
pip install -e '.[dev]'
pytest
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
```

The separation is deliberate: logic changes can be verified headlessly (e.g. in
a cloud/CI session), while the visual layer is reviewed by running it locally.
