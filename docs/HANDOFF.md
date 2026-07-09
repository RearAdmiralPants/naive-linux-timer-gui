# Handoff notes

Context for picking this project back up — especially in a **fresh Claude Code
session** (e.g. the local CLI), since a Claude Code conversation's memory does
not transfer between the web/mobile app and a local terminal session. The code
travels via git; this document travels the *reasoning* that isn't obvious from
the diff.

_Last updated: 2026-07-09, after the glass shard landed on `main`._

The project brief that started all of this is `CLAUDE.md` at the repo root —
read it first. It states the actual goal (probing accelerated 3D across
consumer Linux GPU stacks) and how the user wants to be worked with.

## Lesson from the first local run

The cloud session shipped 38 green tests and an app that **aborted before
drawing a pixel**: `_AlertPlayer` passed `QSoundEffect.Infinite` (an enum) to
`setLoopCount`, which under PySide6 6.11 wants an `int`. Compile-checking
`app.py` could never have caught it, and no model test touches Qt.

The fix is one line. The lesson is the important part: **"the logic is
headlessly testable" is not the same as "the app starts."** `tests/
test_gui_smoke.py` now constructs the Qt objects rather than merely importing
them. It fails on the pre-fix code; that was verified, not assumed.

It has two tiers, because once the shard arrived, `MainWindow` began building a
`QOpenGLWidget` — and Qt's `offscreen` platform has no OpenGL, so constructing
one *segfaults* instead of raising. GL-free assertions (alert player, shard
geometry, text texture) always run; `MainWindow` runs only where GL exists.
`xvfb-run -a` supplies real GL headlessly via Mesa's software rasteriser, so
the cloud container keeps its safety net.

A corollary worth remembering: the skip guard must be checked in `setUp`, not
in a class decorator. Decorators evaluate at import, before `QApplication`
exists, when `platformName()` is still empty — which let the GL test run under
`offscreen` and *not* crash, which is worse than crashing.

Separately, PySide6 wheels don't bundle `libxcb-cursor0`, which Qt 6.5+ needs
for the `xcb` platform plugin. It's a `sudo apt install`, now in the README.

## Where things stand

Two features, both working:

- **Stopwatch** — start/pause/resume/reset, lap support in the model,
  `HH:MM:SS.cs` readout.
- **Timer (countdown / alarm)** — Duration mode (`12m`, `1h30m`, `90s`,
  `25:00`) and Alarm-at mode (`02:54`, `6:30pm`, rolls to tomorrow if past).
  On zero: visual flash + a gentle chime looping ~2 min or until Dismiss.

42 tests. All pass with a display; headlessly, the GL tier needs `xvfb-run`
(see *Running locally*).

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
| `src/naive_timer/app.py` | PySide6 tabbed GUI (thin view) | ⚠️ constructed only |
| `src/naive_timer/shard.py` | OpenGL glass shard; text→texture | ⚠️ geometry + texture only |
| `src/naive_timer/tuning.py` | Dev-only live shader sliders | ✗ |
| `src/naive_timer/shaders/` | `shard.vert` / `shard.frag`, hot-reloaded | ✗ |

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
3. **Alert = shard fracture + dark-red pulse + looping chime for 120 s.** The
   duration is a parameter (`Countdown.alert_duration`). The original red
   *background flash* was cut as too jarring; the alert is now carried entirely
   by the shard. The chime character is hardcoded in `sound.py`.

## Open questions (waiting on in-person / on-workstation review)

Answered at the first local run:

- [x] **Visual alert**: the red flash is **too busy / jarring**. Superseded by
  the shard treatment below — on finish the shard breaks apart and pulses to a
  mostly-transparent dark red at ~1–2 Hz until reset.
- [x] **Spinner**: the orbiting-dots ring is distracting and is being
  **removed**, not kept alongside the 3D view.

- [x] **Chime**: approved. "As subtle as I wanted." Leave volume at 0.35.
- [x] **Etched vs. emissive**: both wanted -- etching, plus an *understated*
  emissivity. Not either/or; the `uEtch` blend stays.

## Backlog

Everything outstanding, so nothing gets lost between sessions. Roughly ordered
by dependency, not by priority.

**Glass and geometry** — branch `feat/glass-volume` (in progress)

- [x] **Thickness.** Extruded into a solid: front face, front bevel, side wall,
  back bevel, back face — 8 triangles per wedge. The bevel is what reads as
  glass; it rakes a highlight along the silhouette, which a flat polygon can
  never do. Highlights roll off (Reinhard) rather than clipping to white.
- [x] **Shatter as rigid bodies.** Each wedge now carries its own pivot,
  linear velocity and angular velocity (`aPieceCenter` / `aPieceVel` /
  `aPieceAxis`), integrated in the vertex shader against elapsed `uShatterT`.
  Pieces tumble about *their own* centroids and recede under gravity. The old
  pinwheel came from rotating every piece about the shard's centre.
- [ ] **Etch pixelation at grazing angles.** `shard.frag` scales the glyph
  coverage gradient (`dFdx`/`dFdy`) by a flat `18.0`. Screen-space derivatives
  blow up where the face turns away from the camera, so engraving edges alias.
  Needs clamping, or a gradient computed in texture space.

Notes for whoever touches the shatter next:

- Velocities have **negative z**: pieces recede and shrink. Positive z threw
  them at the camera, where they ballooned and filled the frame.
- `_SHATTER_CLEAR_S = 5.5` was **measured** by rendering the sequence and
  counting non-background pixels, not guessed. Past it, `paintGL` returns
  early — the alert runs 120 s and there is nothing left to rasterise.
- Gravity dominates the trajectory (≈4.8 units of fall by 5.5 s), so halving
  the linear speeds does *not* strand a piece on screen. If you retune, the
  test that bites is `test_pieces_are_gone_by_the_declared_clear_time`.
- The break is deterministic (`_hash01`, not `random`) so a bad-looking tumble
  reproduces and can be pinned.

**Colour controls**

- [ ] **Hex `RRGGBB` entry** for text/glow colour, replacing the preset combo.
- [ ] **Adjustable light colour.** Currently white and implicit in the shader;
  needs a `uLightColor` uniform and a picker.
- [ ] Keep the `uEtch` blend: the wanted look is etching *plus* an understated
  emissivity, not either/or.

**Background** — its own branch, deliberately later

- [ ] **Starfield + nebulae** behind the shard, replacing the flat dark clear
  colour. Easier to judge the glass against it once the glass has real depth.
  Ignore the backgrounds in the `graphics/` reference images; only the shards
  themselves are representative.

**Sound** — deferred, see *Asset licensing* below

- [ ] **Shatter sound on fracture.** Must be synthesized or CC0; see below.
- [ ] Sequence it with the visual shatter, under the existing looping chime.
- [ ] `QSoundEffect` decodes **only uncompressed WAV**. Compressed formats need
  `QMediaPlayer` + `QAudioOutput`.

**Unbuilt feature from `CLAUDE.md`**

- [ ] **Clock mode.** "Alternatively, the current time is displayed using the
  default visualization techniques until the application is closed." Never
  implemented. A third tab, or an idle state, rendering wall-clock time on the
  shard.

**Older open questions**

- [ ] **Minutes-vs-seconds** default for bare numbers (see choice #1).
- [ ] Whether to surface **config** (sound file, alert duration) in the UI.
- [ ] **Hardware breadth.** `CLAUDE.md`'s stated purpose is to probe 3D across
  consumer Linux GPU stacks. Only tested on Intel Iris Xe / Mesa 25.2 /
  OpenGL 4.6 core. Untested on NVIDIA and AMD.

## Asset licensing (read before adding any binary)

`graphics/` and `audio/` are **gitignored on purpose**, and both have been
moved outside the working tree. They held third-party reference material: a
watermarked Adobe Stock comp (`falling-shard.jpg`, stock #769496700), Craiyon
output (`shard-in-sky.jpg`), scraped product photography, and three glass
shatter recordings captured from YouTube via Audacity.

**Why the audio can't ship, not merely can't be committed.** A modified copy of
a copyrighted recording is still a derivative work. Resampling, attenuating,
and time-stretching a YouTube rip does not launder its provenance, so those
FLACs cannot go into an MIT-licensed app in *any* processed form.

**What we can keep.** Everything, as *reference*, on local disk outside the
repo — which is where they now live. Listening to them to decide what the
synthesized shatter should sound like is ordinary study, not redistribution.
The same goes for the images: `two-shards.jpg` remains the reference for the
bevel and thickness. Nothing has been lost; it simply isn't tracked.

**What shipped audio must be.** Either **CC0/public domain** (Freesound has
good glass-breaking recordings) with an `audio/CREDITS.md`, or **synthesized at
runtime** the way `sound.py` generates the chime.

Synthesis is the better fit, not just the safer one. A shatter decomposes into
a filtered noise burst plus a scatter of high-frequency resonant partials with
staggered decays. That makes *quieter* and *longer* — the two changes wanted
for the reference clips (they peak near −6 dB and run 1.5–2.6 s) — into
parameters rather than ffmpeg passes. It also keeps the repo binary-free, which
is the property that lets this project be developed headlessly in a container.

Note also: **`QSoundEffect` only decodes uncompressed WAV.** Pointing it at a
FLAC yields `Status.Error` and silence — verified. Playing compressed audio
needs `QMediaPlayer` + `QAudioOutput`.

## The 3D shard (done — see `shard.py`)

The timer/stopwatch text is a **dynamic texture on the face of an angled glass
shard**, lit from offscreen. It replaced the spinner and the red flash alert.

- Route: `QOpenGLWidget` + hand-written GLSL (QtQuick3D / Qt3D / QtWebEngine
  all ship with PySide6-Addons, but raw GL is the least fight for custom
  lighting). Confirmed OpenGL 4.6 core on Mesa.
- Text → `QPainter` into a `QImage` → `QOpenGLTexture` → sampled by the
  fragment shader. **`format_elapsed` is the seam**: the models stay UI-free
  and headlessly testable, and the GL widget is just another thin view.
- Shaders **hot-reload on save** (`QFileSystemWatcher`); a failed compile prints
  the error and keeps the last good program. `NAIVE_TIMER_TUNE=1` opens a live
  slider panel. Tune on the real GPU — there is no port step.
- Both tabs share one `ShardParams`, so the sliders drive both shards.

### PySide6 traps found the hard way

Two silent overload-resolution bugs, same family, neither catchable by a
compile check:

1. `setLoopCount(QSoundEffect.Infinite)` — the enum is no longer implicitly an
   `int`; raised `TypeError` and aborted the app before it drew a pixel.
2. `setUniformValue(location, 0.55)` binds to the **int** overload and
   truncates to `0`. That zeroed `uBaseAlpha`, so the shard rendered fully
   transparent, with no error anywhere. Floats must go through
   `setUniformValue1f`.

When a PySide6 call takes a Python number, check which overload it actually
resolves to.

## Running locally

```bash
sudo apt install libxcb-cursor0 xvfb        # xcb plugin dep + headless GL; not in the wheel
python3 -m venv .venv                       # system Python is externally managed
.venv/bin/python -m pip install -e ".[dev]"

.venv/bin/python -m unittest discover -s tests -v   # with a display: everything
xvfb-run -a .venv/bin/python -m unittest discover -s tests -v   # headless, incl. GL tier

.venv/bin/python -m naive_timer                     # see/hear the GUI
NAIVE_TIMER_TUNE=1 .venv/bin/python -m naive_timer  # ... with the shader tuning panel
```

Without a display **and** without `xvfb-run`, the GL tier of the smoke test
skips itself: Qt's `offscreen` platform has no OpenGL, and constructing a
`QOpenGLWidget` under it *segfaults* rather than raising. Use `xvfb-run` in CI.

## Branches

`main` carries the shard. Active work is on **`feat/glass-volume`**
(extrusion → rigid-body shatter → etch aliasing → colour controls). The
starfield and the synthesized shatter sound get their own branches afterwards.
No PR has been opened yet.
