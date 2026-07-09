# naive-linux-timer-gui

A simple stopwatch/timer running in Linux with naive 3D/animation features.

Built with [PySide6](https://doc.qt.io/qtforpython/) (Qt for Python). The
timekeeping logic is kept UI-free and fully unit-tested, so it can be developed
and verified without a display; the Qt layer is a thin view on top.

## Features

- Start / pause / resume / reset stopwatch
- `HH:MM:SS.cs` readout at ~60 FPS
- Lap support in the core model
- A naive animated pseudo-3D spinner (rotating gradient ring with orbiting
  dots) that spins faster while running — a starting point for fancier effects

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
  stopwatch.py   # pure timekeeping model (no Qt) — unit-tested
  app.py         # PySide6 window + animated spinner (thin view)
  __main__.py    # enables `python -m naive_timer`
tests/
  test_stopwatch.py
```

The separation is deliberate: logic changes can be verified headlessly (e.g. in
a cloud/CI session), while the visual layer is reviewed by running it locally.
