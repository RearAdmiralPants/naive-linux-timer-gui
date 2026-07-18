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
- [x] **Etch speckle on glyph edges** — fixed. *Not* a grazing-angle effect;
  that was a wrong guess, disproved by rendering the same camera angle at
  `etch = 0` (clean) and `etch = 1` (speckled). The shader perturbed the normal
  by the *screen-space* derivative of glyph coverage, scaled by a flat `18.0`.
  `dFdx`/`dFdy` are evaluated once per 2×2 pixel quad, so across a magnified
  glyph edge the derivative is ~0 inside a quad and jumps at quad boundaries.
  It now takes a **central difference in texture space**, stepping by
  `max(texel, fwidth(vUV))` — at least one texel, and never finer than the
  pixel's own footprint. `fwidth` is still a screen derivative, but of `vUV`,
  which varies smoothly across the face, so it adds no speckle of its own.
  The tilt is now the `etch_depth` param (default 3.0), not a magic `18.0`.

  **How to measure this artefact.** `dFdx` freezes a value across each 2×2
  quad, so its signature is that horizontally adjacent pixels *inside* a quad
  agree while pairs *straddling* a quad boundary jump. Take the mean absolute
  luminance difference for each group; their ratio was **2.46** before and
  **1.05** after (1.0 = no quad structure). Two earlier metrics were useless
  and nearly misled me: counting "salt-and-pepper" pixels went *up* after the
  fix, because it counted the new engraved rim highlight; counting hard
  luminance steps was flat, because those are the glyph's own colour edge.
  Measure the artefact, not a proxy for it.

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
- Wedges are **closed solids**: each carries the two radial cut faces where it
  met its neighbours, flagged `aCap` and discarded by the fragment shader while
  the shard is whole (they are interior surfaces then, and would muddy the
  glass). Without them the tumbling pieces looked hollow edge-on.
- Facet winding is judged against the **wedge's** centroid, not the shard's.
  The shard's axis lies inside both cut planes, so a cap's normal is
  near-perpendicular to the direction from the shard centre and that dot
  product's sign is noise.
- The alarm **tints** the lit surface rather than replacing it. Mixing straight
  to a flat red erased all shading at each pulse peak, so the wedges became red
  silhouettes and their per-piece lighting was invisible half the time.

### How to check a shader change actually did something

Render and measure; do not reason about it. Each of these caught a real bug:

- *Is it lit?* Move the light, count changed pixels. (0 changed at the alarm
  peak proved the shading was being discarded.)
- *Did the pose survive?* Compare silhouette masks across the frame boundary.
  (0.01% mismatch when the spin is preserved; 31% when it snaps to rest.)
- *Is it drawing at all?* Force `FragColor` to a solid colour, then sample
  pixel values. (One distinct colour on screen meant alpha was 0.)

**Colour controls**

- [ ] **Hex `RRGGBB` entry** for text/glow colour, replacing the preset combo.
- [ ] **Adjustable light colour.** Currently white and implicit in the shader;
  needs a `uLightColor` uniform and a picker.
- [ ] Keep the `uEtch` blend: the wanted look is etching *plus* an understated
  emissivity, not either/or.

**Background** — branch `feat/starfield`

- [x] **Starfield + nebulae**, generated procedurally in `shaders/sky.{vert,frag}`
  and drawn as a fullscreen pass before the shard. No image asset: nothing to
  license, and it resamples at any window size. Three star layers (hash grid,
  rare bright stars via a high power, desynchronised twinkle) plus a
  domain-warped fBm nebula.
- [x] **It is a real skybox, not a wallpaper.** The noise is evaluated in world
  space along a per-pixel view ray rebuilt from the camera basis, so the sky
  lives on the celestial sphere: it rotates with the view and never
  translates, which is how objects at infinity behave. The first version was
  screen-space (`vUV` only) and would have stayed glued to the glass the
  moment the camera moved.
- [x] **The camera sways**, it does not orbit. See below.

Cost: roughly **2.3–4.4 ms/frame** for the whole scene at 420x620 — a wide
spread, because an integrated GPU with dynamic clocks gives noisy single
samples. Call it well under half a 60 fps budget. It is clearly dearer than the
screen-space version (~0.6 ms), since 3D value noise needs 8 lattice hashes per
octave against 2D's 4, twice over for the domain warp. Cheap enough to keep. If
it ever matters: fewer octaves, or bake the sky into a cubemap once.

Do not quote a single benchmark run to three significant figures, as an earlier
version of this file did. Run it several times and give the range.

### Why the camera sways instead of orbiting

A full 360° orbit leaves the front face edge-on at 90° and mirrored (seen
through the translucent glass) at 180°, so the readout is illegible for roughly
half of every cycle. **This is a timer**; the numerals are the point. The camera
therefore sweeps a bounded arc across the front — `sway_degrees = 30` either
side — on a sine, which eases at the reversals with no visible corner. Worst
front-face facing over a whole cycle is 0.84 (≈33° off-axis).

`sway_degrees = 180` restores the full orbit if you want the sculpture rather
than the clock. `test_camera_never_swings_behind_the_numerals` will fail if you
make that the default (it reports facing −0.98).

The shard no longer carries a fixed model rotation, and its `idle_spin` now
defaults to 0: tilting the object while also orbiting the eye fights itself.
Both passes read the same `ShardWidget.camera()`; if they ever disagreed, the
backdrop would slide against the geometry.
- The sky pass must run **before** `paintGL`'s early return for
  `pieces_have_cleared`, or the backdrop disappears for the ~115 s the alert
  outlives the shard. Pinned by a test.
- `glClearColor` is black on purpose. The sky covers every pixel, so the clear
  colour is only visible when the backdrop fails — and it should then look
  obviously broken. It was previously a dark blue-grey *brighter* than the
  nebula's own void colour, which made a "did the sky draw?" test pass even
  with the sky pass deleted.

**Sound** — branch `feat/shatter-sound`

- [x] **Shatter sound on fracture**, synthesized in `sound.py`. Three layers:
  an impact transient (a high-passed noise crack plus a low-passed body), a set
  of inharmonic resonant partials, and a long thinning scatter of fragment
  grains. Deterministic per `seed`; `amplitude` is the peak *after*
  normalisation, so it means headroom directly.
- [x] Plays once at the break, under the looping chime. Both files are
  synthesized at runtime; still no binary assets.
- [x] Temp files are now per-uid and versioned
  (`naive_timer_shatter_<uid>_v<N>.wav`). `/tmp` is shared, so the old fixed
  name collided between users; and without the version suffix, editing the
  synthesis silently served a stale cached WAV.

Tuned **against the reference recordings**, not by ear (they cannot be shipped,
but measuring them is fair use of a listening reference):

| clip | dur s | peak dB | ZCR Hz | decay→10% |
|------|------:|--------:|-------:|----------:|
| synth | 2.60 | −13.2 | 9824 | 1.3 s |
| ref1 | 1.56 | −6.1 | 8316 | 1.1 s |
| ref2 | 1.72 | −5.5 | 9143 | 1.2 s |
| ref3 | 2.65 | −6.4 | 6228 | 0.1 s |

Zero-crossing rate is a cheap brightness proxy. The first synth version had all
its partials above 1200 Hz and measured **13.2 kHz** — it would have read as a
cymbal, not glass. A third of the resonances now sit at 180–900 Hz, in the body
of the pane, and a low-passed noise "crunch" was added under the crack.

`_add_decaying_sine` uses a two-term sine recurrence rather than `math.sin` per
sample: ~140 partials over 100k+ samples took 1.9 s to generate (a visible
freeze at startup, since `_AlertPlayer` is built in `MainWindow.__init__`) and
now takes 0.56 s.

Still true: **`QSoundEffect` decodes only uncompressed WAV.** It errors on FLAC.
Compressed formats need `QMediaPlayer` + `QAudioOutput`.

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
sudo apt install python3-venv               # ensurepip; Debian/Ubuntu split it out

./launch.sh                     # creates .venv on first run, then see/hear the GUI
NAIVE_TIMER_TUNE=0 ./launch.sh  # ... without the shader tuning panel
```

`launch.sh` re-installs whenever `pyproject.toml` changes, keyed on a hash it
stores in `.venv/.pyproject.sha256`. It installs `-e .`, not `-e ".[dev]"` — the
tests below are stdlib `unittest`, so they need no extras. For the `[dev]` pytest
extra, install into the venv the script built:

```bash
.venv/bin/python -m pip install -e ".[dev]"

.venv/bin/python -m unittest discover -s tests -v   # with a display: everything
xvfb-run -a .venv/bin/python -m unittest discover -s tests -v   # headless, incl. GL tier
```

### Which GPU it runs on

On a hybrid-graphics machine, OpenGL goes to the **integrated** GPU unless a
program asks otherwise — which at 4K is the difference between a smooth app and
a slideshow. Select a GPU with `--gpu`:

```bash
./launch.sh --gpu list      # what does this machine have?
./launch.sh --gpu nvidia    # discrete, via PRIME offload
./launch.sh --gpu intel     # integrated
./launch.sh                 # whatever the system picks (usually integrated)
```

This is a **GLX vendor switch, not CUDA**. The app is OpenGL 3.3 core and never
touches CUDA; an AMD card would be selected the same way, via `DRI_PRIME`. The
mechanics live in `gpu-select.sh`, shared by `launch.sh` and the benchmark.

**Do not assume the discrete GPU wins.** It depends entirely on the pairing, and
PRIME copies every rendered frame back to the display-connected iGPU, which at
4K is not free. Measure with `tools/bench-gpu.sh`, which times the real
`sky.frag` on each GPU at the display's resolution:

```bash
tools/bench-gpu.sh              # display resolution
tools/bench-gpu.sh 1920 1080    # or an explicit one
```

Measured on the RTX 3050 box at 3840x2400 (`sky.frag` only — this excludes the
shard, and excludes PRIME's copy-back, so both columns are optimistic):

| GPU | ms/frame | ceiling |
| --- | --- | --- |
| Intel UHD (TGL GT1) | 58.3 | 17 FPS |
| RTX 3050 Laptop (PRIME offload) | 7.1 | 140 FPS |

The budget is 16 ms (`FRAME_MS` in `app.py`), so the iGPU misses it by 3.6x.

Note the scaling: 4x the pixels costs the Intel 4.03x the time. `sky.frag` is
cleanly fill-rate bound, which means **resolution is the whole story** and a
faster GPU only buys headroom against an extravagant per-pixel cost.

### The nebula is baked into a cubemap (this is now done)

`tools/bench_sky.py` compiles `sky.frag` several ways and times each, so the
frame can be attributed rather than guessed. Measured on a **TigerLake GT2
(Iris Xe)** — note that is *not* the GT1 in the table above, which is roughly
half the part; conflicting historical numbers here are two different machines,
one 1920x1080 and one 3840x2400.

| | 420x620 | 1920x1080 | 3840x2400 |
| --- | --- | --- | --- |
| before (all procedural) | 0.63 ms | 4.4–6.7 ms | 27–30 ms |
| **after (nebula baked)** | — | **1.2 ms** | **6.5 ms** |
| stars alone | 0.18 | 1.2 | 7.8 |
| fill-rate floor | 0.06 | 0.2 | 1.2 |

**The nebula was 78–98% of the frame; the stars are 14–26%.** That split held
at every resolution and on both GPUs, and it is what decided the design:

- **Bake the nebula.** Low-frequency, blurry, expensive — exactly what a
  texture is good at. Filtering artefacts are invisible on a domain-warped fbm.
- **Keep the stars procedural.** Sub-pixel bright points are exactly what a
  texture is *worst* at: bilinear smears the cores, mips erase them, and camera
  sway makes them shimmer and pop between texels. They are also cheap. Baking
  them would have cost the crispness and the per-star twinkle to save ~20%.

Reducing fbm octaves was tried first and rejected — 5→3 only reached 16.6 ms at
4K, still over budget, and 2 octaves (10.7 ms) stops producing filaments.

**What the cube stores** (`nebulaFactors()` in `sky.frag`): two direction-only
scalars, RG16F, 512² per face, 3 MB total. `.x` is cloud thickness before
`uNebula` scales it; `.y` is the position between the two lobe colours.
Everything colour-dependent stays a live uniform, so **`nebula`,
`nebula_color_a` and `nebula_color_b` still respond to the tuning sliders with
no re-bake** — only a shader edit triggers one.

`_bake_nebula()` in `shard.py` renders the six faces with
`SKY_PROCEDURAL_NEBULA + SKY_BAKE` defined, using `_CUBE_FACE_BASES`, which
reproduces the GL spec's own `(ma, sc, tc)` face convention. Get one axis sign
wrong and the sky comes back mirrored across a face boundary; verified by
rendering the same view both ways, max deviation **1/255** including a corner
view spanning three faces and a pole view. `GL_TEXTURE_CUBE_MAP_SEAMLESS` is
enabled, without which bilinear taps clamp at face edges and draw seams.

Cost of a bake: 6 × 512² = 1.6 Mpx, about one-sixth of a single 4K frame — so
it is redone on every shader hot-reload rather than cached to disk.

**What was given up:** the nebula's drift (0.004 units/s) is gone; a snapshot
cannot drift. If it is ever missed, re-bake one face per frame on a rolling
basis for 1/6 the cost. Star twinkle is untouched.

Do not read `full` from the bench as the shipped number any more — that variant
is the *pre-bake* shader, kept so the saving stays measurable. `baked` is what
ships. The bench also loads `default-params.json` (`star_density=178`) rather
than `ShardParams` defaults (`90`), so its star cost is the pessimistic one.

**Thermal noise is worse than previously documented.** The same 5-octave shader
at 4K measured 21.8, 26.4 and 62.0 ms in one session depending on how
heat-soaked the iGPU was. That is a 3x spread, not sampling jitter. Insert
cooldowns between 4K runs. The 58.3 ms figure above may itself be heat-soaked.

**The T500 is only ~1.3x the Iris Xe** (3.5 vs 4.5 ms at 1080p). Once PRIME's
per-frame copy-back is counted, offloading to it on that machine is plausibly a
net loss. `gpu-select.sh` should not assume discrete is faster.

### Animation runs on real elapsed time, not a fixed step

`_tick()` used to call `advance(FRAME_MS / 1000.0)` — a constant 16 ms —
regardless of how long the frame actually took. On a GPU that could not hold
60 FPS the camera sway, star twinkle and nebula drift therefore ran in slow
motion: at 27 ms/frame, 60% speed. The *displayed time* was always correct
(that comes from the models, which read the wall clock), which is why this went
unnoticed for so long; it was only the animation that lagged. It also meant any
`sway_degrees` or `orbit_speed` value tuned on a fast machine felt different on
a slow one.

`FrameClock` in `app.py` now measures the real interval with `QElapsedTimer`,
clamped to `MAX_FRAME_S = 0.25` so a stall or a laptop resume makes the camera
sway rather than teleport.

### Known: `default-params.json` does not apply to a normal launch

`_autoload()` is a method of the tuning panel (`tuning.py:220`), and the panel
is only constructed under `NAIVE_TIMER_TUNE=1`. So the promoted look — red
numerals, `star_density=178`, the tuned nebula — is what you get in tune mode,
and a plain `python -m naive_timer` still renders `ShardParams` defaults. That
is probably not the intent of "auto-load default-params.json"; left alone here
because fixing it changes the app's appearance, which is a decision, not a bug
fix.

Without a display **and** without `xvfb-run`, the GL tier of the smoke test
skips itself: Qt's `offscreen` platform has no OpenGL, and constructing a
`QOpenGLWidget` under it *segfaults* rather than raising. Use `xvfb-run` in CI.

## Branches

`main` carries the shard. Active work is on **`feat/glass-volume`**
(extrusion → rigid-body shatter → etch aliasing → colour controls). The
starfield and the synthesized shatter sound get their own branches afterwards.
No PR has been opened yet.
