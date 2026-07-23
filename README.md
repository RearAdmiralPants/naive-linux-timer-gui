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
./launch.sh
```

That creates `.venv` on first run, installs the project into it, and starts the
app. It re-installs whenever `pyproject.toml` changes, so a new dependency never
leaves you on a stale environment. Arguments are forwarded to the app.

On a laptop with both an integrated and a discrete GPU, OpenGL uses the
integrated one unless asked otherwise — and at 4K that can be the difference
between 17 and 140 FPS. Pick explicitly:

```bash
./launch.sh --gpu list      # what GPUs does this machine have?
./launch.sh --gpu nvidia    # the discrete GPU, via PRIME offload
./launch.sh --gpu intel     # the integrated GPU
```

Whether the discrete GPU is actually faster depends on the pairing, so measure
rather than assume — `tools/bench-gpu.sh` times the real sky shader on each GPU
at your display's resolution. See [docs/HANDOFF.md](docs/HANDOFF.md) for what
the numbers mean.

Creating the virtualenv needs `ensurepip`, which Debian and Ubuntu split into a
separate package. If `launch.sh` tells you it is missing:

```bash
sudo apt install python3-venv
```

The equivalent by hand, if you would rather not use the script:

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

`tests/test_gui_smoke.py` additionally constructs the Qt objects. It exists
because the model tests can be entirely green while the app crashes on startup
— which is exactly what happened once.

It has two tiers, because Qt's `offscreen` platform has **no OpenGL**, and
constructing a `QOpenGLWidget` under it *segfaults* rather than raising:

```bash
# Tier 1 only. Alert player, shard geometry, text texture. Skips the GL tier.
.venv/bin/python -m unittest discover -s tests -v

# Both tiers, still headless: a virtual X server gives real GL via Mesa.
xvfb-run -a .venv/bin/python -m unittest discover -s tests -v
```

With a display attached, both tiers run automatically. Use the `xvfb-run` form
in CI and cloud containers — otherwise the shard is never actually constructed.

## Tuning the shard

The timer text is rendered as a texture on the face of a lit glass shard. Its
fragment shader lives in `src/naive_timer/shaders/shard.frag` and is
**hot-reloaded**: edit it while the app runs and it recompiles on save. A
shader that fails to compile prints the error and leaves the previous one
running, so you cannot break the app from there.

```bash
./launch.sh                      # the panel is on by default
NAIVE_TIMER_TUNE=0 ./launch.sh   # ... without it
```

That adds a panel with live sliders for every uniform — light position,
specular power, Fresnel, glow, and an etched↔emissive blend — plus font and
colour pickers. **Print params** dumps the current values to the console in a
form you can paste back into `ShardParams`.

A look saved from that panel is just a JSON file, and `--json` loads one at
startup — the shard wears it from the first frame:

```bash
./launch.sh --json green-nebula.json          # load a saved look
./launch.sh --no-panel                         # tuning env set, but no panel
NAIVE_TIMER_TUNE=1 ./launch.sh --json green-nebula.json  # load it, then tweak
```

`--json` only loads params; it no longer touches the panel. The panel is
governed solely by `NAIVE_TIMER_TUNE`, and `--no-panel` forces it off — so you
can load a look for a clean screenshot, or load one as a starting point and keep
dragging sliders. Run `naive-timer --help` for the full list. (Unknown keys in
the file are ignored, so a look saved by an older or newer build still loads what
it can.)

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
  test_cli.py        # CLI parsing + JSON param loading (headless, no Qt)
  test_gui_smoke.py  # constructs the Qt widgets offscreen (needs PySide6)
```

The separation is deliberate: logic changes can be verified headlessly (e.g. in
a cloud/CI session), while the visual layer is reviewed by running it locally.
