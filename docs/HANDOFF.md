# Handoff notes

Context for picking this project back up — especially in a **fresh Claude Code
session** (e.g. the local CLI), since a Claude Code conversation's memory does
not transfer between the web/mobile app and a local terminal session. The code
travels via git; this document travels the *reasoning* that isn't obvious from
the diff.

_Last updated: 2026-09-09, after the strobe and the non-expiring alert landed
on `feat/shatter-lights-flash`. (Shatter glints: 2026-09-08. HDR lighting
pipeline: 2026-08-10.)_

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

131 tests. All pass with a display; headlessly, the GL tier needs `xvfb-run`
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
| `src/naive_timer/shard.py` | OpenGL glass shard; text→texture; the HDR passes | ⚠️ geometry + texture only |
| `src/naive_timer/tuning.py` | Dev-only live shader sliders | ✗ |
| `src/naive_timer/shaders/` | `shard.*`, `sky.*`, `post_*.frag`, all hot-reloaded | ✗ |

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
3. **Alert = shard fracture + glinting pieces + looping chime for 120 s.** The
   duration is a parameter (`Countdown.alert_duration`). The original red
   *background flash* was cut as too jarring; so, later, was the dark-red pulse
   that replaced it. The alert is now carried entirely by the shard breaking
   and by the pieces flashing as they fall (`spark_*` in `ShardParams`). The
   chime character is hardcoded in `sound.py`.

## Open questions (waiting on in-person / on-workstation review)

Answered at the first local run:

- [x] **Visual alert**: the red flash is **too busy / jarring**. Superseded by
  the shard treatment below — on finish the shard breaks apart. The dark-red
  pulse that carried the first version of that is **gone too** (2026-09-08);
  what announces the break now is the pieces catching the light as they tumble.
  See *Shatter glints* below.
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
  never do. Highlights roll off (Reinhard) rather than clipping to white —
  though that roll-off no longer happens here; it moved to the composite pass
  when the renderer went HDR.
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
- `shatter_clear_s = 5.5` (a `ShardParams` field now, not the old
  `_SHATTER_CLEAR_S` constant) was **measured** by rendering the sequence and
  counting non-background pixels, not guessed. Past it, `_draw_shard` returns
  early — the alert runs 120 s and there is nothing left to rasterise. It is
  only an upper bound: `_all_pieces_offscreen` re-tests a few times a second and
  stops drawing as soon as the wedges are actually gone. That test is
  deliberately *not* latched, because a wide sway (or `sway_degrees = 180`) can
  sweep the camera back toward a piece that had left the frame.
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
- **Shatter glints** (`spark_*`) replaced the red pulse. Transient point
  lights are spawned beside the falling wedges; `_spark_lights` in `shard.py`
  places them and `shard.frag` lights from them. Nothing draws the light
  itself — everything you see is what the glass reflects, and the glare and
  lens flare come for free because a hot facet clears the bright-pass on its
  own. Points worth knowing before touching it:
  - **Stateless.** A spark is a pure function of the break clock: spark *k* is
    born in its own `1/rate` slot, jittered inside it, so nothing accumulates,
    a reset needs no cleanup, and a break sparkles identically every run (same
    reasoning as `_hash01` for the tumble). Only the *k*s whose slot can still
    overlap now are evaluated, so cost does not grow with elapsed shatter time.
  - **Placed in the camera-facing hemisphere**, 12°–68° off the view axis,
    on a sphere of `spark_offset` wedge-radii around the piece it belongs to.
    A uniformly random direction lights the piece just as well, but half those
    highlights fire away from the viewer and are never seen — and being seen is
    the entire point of forcing what used to happen by luck.
  - **Specular-biased, and this was measured.** At the key light's own weights
    (diffuse 0.40, Fresnel 1.0) a spark reads as a *flashbulb*: whole wedges go
    evenly pink-white and the facets wash out instead of standing out. Blown
    pixels (>0.97 luma) went from 1.4–3.8% of frame with no sparks to 10–22%
    with them, across the frame rather than in spots. Diffuse is down to 0.10
    and Fresnel to 0.35, `spark_intensity` came down from 26 to 14, and the
    same measurement now reads 3–6% concentrated on individual pieces.
  - **`spark_focus` narrows the lobe** (× `spec_power`). It exists because the
    presets on disk run `spec_power` from 9.45 to 40: at the low end the key
    light's own highlight covers a whole facet, and a spark using the same
    exponent turns its wedge into a lit paper triangle.
  - **Falloff is local on purpose.** `spark_reach` (half strength at that
    distance) must stay under the separation between wedges, or every piece
    flashes together and it reads as the whole field pulsing.
  - `spark_flare` multiplies `flare` while the pieces are falling. The idle
    flare is deliberately timid to keep ghosts off the numerals; once the shard
    is in pieces there is no readout left to protect.
  - **The crack has its own light** (`spark_impact`), and it is not a glint: a
    step and an exponential decay rather than a swell, placed around the
    shard's centre rather than a wedge's, and untinted. Its shape and its
    0.30 s life are read off `sound.py`'s shatter clip — a 1.5 ms raised-cosine
    open, a 50 ms noise burst, a body decaying over a few hundred ms — because
    `_begin_alert` plays that clip on the same line that breaks the shard, so
    the two are the same event. `spark_rate` and `spark_impact` are separate
    switches for exactly this reason: the scatter can be turned off and the
    crack still fires.
  - **`spark_hue` is dispersion**, and it mixes toward a random saturated hue
    rather than rotating the lamp's. Rotating was tried first and does nothing:
    most presets light with something near white, which has no hue to rotate,
    and what dispersion does to a white reflection is *add* colour. It is
    subtler than the number looks — mean saturation over the lit, unclipped
    pixels goes 0.320 (off) → 0.341 (0.3) → 0.378 (0.75) — because the glass's
    own colour is most of a lit facet and the hot core is white whatever
    reached it. Tints only take channels down: a prism splits the energy it
    gets, it does not add any.
  - The shader loop is bounded by `_SPARK_MAX` / `MAX_SPARKS` — **the two must
    agree**. When more sparks are alive than that, the brightest survive.
    While the shard is intact `uSparkCount` is 0, so this costs nothing until
    the break.

### The alert does not end by itself (2026-09-09)

The countdown's `alert_duration` (120 s) now governs only the **chime**. The
visual alert -- break, glints, strobe -- runs until the user dismisses it,
starts another countdown, or leaves for the Stopwatch tab. The seam is one line
in `TimerWidget._sync_alert_player`: `imminent` is
`self._alerting and self._cd.alert_active()`, so when the audible window closes
the player is released (which is what stops the sound) while `_alerting` stays
true and the shard goes on strobing.

Because it no longer stops on its own, **every exit has to be wired**. There are
three: Dismiss, starting another countdown (`start()` already called
`_stop_alert`), and `MainWindow._on_tab_changed`. If you add a fourth way to
leave the alert, wire it or the strobe waits behind a tab forever.

### The strobe

`_strobe_alpha` in `shard.py`, `uStrobe`/`uStrobeColor` in
`post_composite.frag`. A flat wash in the light's colour over the finished
frame, starting `strobe_delay_s` after the break, when the pieces have long gone
and an alarm that is still ringing has nothing on screen to show for it.

- **After the tonemap, deliberately.** That is what makes `strobe_peak = 0.7`
  mean "70% of the frame is this colour". Upstream in linear light the number
  would mean nothing (radiance 0.7 of white is a mid grey once the curve has
  had it) and the glare and flare passes would treat the wash as a light
  source and bloom it.
- **Parabolic, and that is the point.** `alpha = peak * |2*phase - 1| **
  shape`: minimum mid-cycle, peak at the edges. At the default shape of 2 it
  sits below half peak for 71% of every cycle, which is what makes it read as
  a pulse in the dark rather than as a light left flickering. Shape 1.0 is a
  triangle wave and looks like a fade; it is pinned by
  `test_most_of_the_cycle_is_spent_dark`.
- **The period and the shape interact**, which matters when retuning. The
  shape's duty is a fraction of the *cycle*, so lengthening the period
  stretches the lit part along with everything else. This was first tuned at
  0.9 opacity and a 1.1 s period -- a flash -- and softened to 0.7 every 4 s,
  which at the same exponent is a 1.2 s swell rather than a 0.3 s flash. If a
  long period should still read as a flash, `strobe_shape` is the lever: at
  4 s, shape 2.0 is above half peak for 1.17 s, 3.5 for 0.72 s, 5.0 for 0.52 s.
- **The phase is offset half a cycle** so the first pulse builds. Opening on
  the cusp put a full-strength flash on the frame the delay expired, which
  reads as a glitch rather than as the start of something.
- **`strobe=False` on `set_alarm`** is what separates an alert from a
  transition. The Stopwatch's Reset breaks the shard the same way, but nothing
  is waiting on the user afterwards -- it reassembles at zero on its own -- so
  it must not pulse. Only the caller knows which kind of break it is.

### The Stopwatch's Reset was silent, and that looked like broken audio

Reported as "no sound at all today". It was not a regression and not the audio
stack: the shatter clip was only ever wired to the countdown's zero-crossing,
so breaking the shard from the Stopwatch -- the quick way to look at the break,
with no countdown to wait out -- had never made a sound. `_ShatterPlayer` now
plays the glass there (no chime; a reset is not an alert).

**How it was diagnosed, because guessing would have cost hours.** `parec` on the
default sink's monitor while the *real app* ran `--timer 4s` under `xvfb-run`,
then RMS per quarter-second window: shatter at peak 0.198, chime looping every
2 s after it. That proved the whole audio path end to end -- WAV, QSoundEffect,
PulseAudio backend, sink routing -- in one measurement, and left the trigger as
the only thing it could be. Recording the sink is the tool to reach for here;
asking whether a human heard something tells you much less, much later.

    parec --device=<sink>.monitor --format=s16le --rate=48000 --channels=2 > cap.raw

### How to check a shader change actually did something

Render and measure; do not reason about it. Each of these caught a real bug:

- *Is it lit?* Move the light, count changed pixels. (0 changed at the alarm
  peak proved the shading was being discarded.)
- *Is the new light doing anything?* Render the same instant of the same break
  twice, `spark_rate` at 0 and at its default, and count bright pixels. At the
  *peak* of a flash, not at the first instant a spark exists — a spark a
  millisecond into its fade-in shows nothing, and a test that lands on one is
  measuring the timing lottery. (`test_the_glints_actually_reach_the_screen`.)
- *Did the pose survive?* Compare silhouette masks across the frame boundary.
  (0.01% mismatch when the spin is preserved; 31% when it snaps to rest.)
- *Is it drawing at all?* Force `FragColor` to a solid colour, then sample
  pixel values. (One distinct colour on screen meant alpha was 0.)

**Colour controls**

- [x] **Hex `RRGGBB` entry** for text/glow colour, replacing the preset combo.
  `_HexColorEdit` in `tuning.py`; it only applies a value once it parses, so
  typing `#ff` on the way to `#ff8800` tints the field red rather than blanking
  the shard.
- [x] **Adjustable light colour.** `uLightColor` plus a picker. `light_intensity`
  arrived later and is deliberately *separate* — see the HDR section.
- [x] Keep the `uEtch` blend: the wanted look is etching *plus* an understated
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
samples. (The HDR post chain adds 0.84 ms at that size; see its own section.)
Call it well under half a 60 fps budget. It is clearly dearer than the
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
- The sky pass must run **before** the early return for `pieces_have_cleared`,
  or the backdrop disappears for the ~115 s the alert outlives the shard. Pinned
  by a test. That return now lives in `_draw_shard`, not in `paintGL`: once
  there were post passes that had to run *after* the geometry, an early return
  from `paintGL` would have taken the tonemap down with it and the window would
  have gone black. Keep it that way — every future "draw nothing this frame"
  case belongs in `_draw_shard`.
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

  The HDR chain widens this gap: `RGBA16F` render targets with 4x MSAA and a
  blit-resolve are new API surface, and the proprietary NVIDIA driver is a
  different implementation of the same GL 3.3 core path. The `[post] targets`
  console line reports the format, the granted sample count and the glare
  resolution on every resize — read it first on any new box. Nothing about the
  chain is vendor-specific in principle, so a difference there is a finding
  worth writing down rather than an expected one.

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

## The "segfaults after ~45 minutes" crash (fixed 2026-08-03)

**It was never the GL code, and it was never a timeout.** Qt 6.11 defaults to a
native **PipeWire audio backend** on Linux. Against PipeWire 1.0.5 (Ubuntu
24.04) that backend takes the whole process down whenever the audio sink it is
attached to goes away.

Fixed by pinning the backend at the top of `app.py`, before anything can
initialise QtMultimedia:

```python
os.environ.setdefault("QT_AUDIO_BACKEND", "PulseAudio")
```

"PulseAudio" still means PipeWire underneath — it is `pipewire-pulse` serving a
libpulse client. The audio path is unchanged; only the client library differs,
and that one survives its server rearranging devices.

### How it was found

Five core dumps were sitting in `coredumpctl` the whole time. **Look there
first**; the console output is nearly useless by comparison.

```bash
coredumpctl list                      # <pid> for each `python -m naive_timer`
coredumpctl debug <pid> --debugger=gdb --debugger-arguments="-batch -ex 'thread apply all bt'"
```

Every one of them crashed on a **PipeWire thread**, not the Qt main thread. Two
signatures, which is why it looked like "several different root causes":

- **SIGSEGV**, null deref at `+0x1c` in `libpipewire-module-protocol-native.so`
  (`si_addr = 0x1c`, `mov 0x1c(%rsi),%edx` with `rsi = 0`). Four of the five.
- **SIGABRT**, glibc `corrupted size vs. prev_size` inside `pw_stream_new_simple`
  — the heap was *already* corrupt, and this allocation merely tripped over it.

The abort's stack is the one that named the mechanism, top to bottom:

```
QPlatformAudioDevices::audioOutputsChanged()
  -> QSoundEffectPrivateWithPlayer::getEngineFor()
    -> QRtAudioEngine::QRtAudioEngine()
      -> QAudioSink::startABIImpl()
        -> pw_stream_new_simple() -> pw_context_new() -> ... -> calloc -> abort
```

So: the device list changes, and Qt tears down and rebuilds an entire
`pw_context` per live sound effect. That rebuild path is what is broken.

### The reproducer

Deterministic — **crashed on the first iteration, every time**:

1. `pactl load-module module-null-sink sink_name=fakebt`, set it default.
2. Start the app (or just construct a `QSoundEffect`).
3. `pactl unload-module <id>` — the sink vanishes underneath it.

That is a Bluetooth headset dropping, in one command. Under
`QT_AUDIO_BACKEND=PulseAudio` the same abuse survived 20/20 iterations, both
idle and mid-playback.

### Two things that were counter-intuitive

- **Nothing has to be playing.** Constructing a `QSoundEffect` opens the stream,
  and `TimerWidget.__init__` builds `_AlertPlayer` at startup. A freshly
  launched app that never rings is fully exposed — which is why crashes turned
  up with no alarm, no lock screen and no user at the keyboard.
- **Adding and removing *other* sinks is harmless.** Only the sink the stream is
  attached to disappearing triggers it. That is why "45 minutes" varied so much:
  it is the wait for a Bluetooth idle-disconnect, a monitor sleeping and taking
  its HDMI sink with it, or a card re-profiling.

The four `QSocketNotifier: Socket notifiers cannot be enabled or disabled from
another thread` warnings that preceded every crash are the same backend
misbehaving across threads. They are a **fingerprint, not the cause** — under
PulseAudio the count goes to zero, and it is a useful one-line check that the
fix is actually in effect.

### If you want to re-test this on a newer PipeWire

`setdefault`, so `QT_AUDIO_BACKEND=PipeWire ./launch.sh` puts the old behaviour
back for exactly that purpose. `tests/test_gui_smoke.py::
test_the_pipewire_audio_backend_is_not_in_use` will fail while it is exported —
deliberately.

## The "Save dialog locks up" bug (fixed 2026-08-12)

**The render loop was starving the file dialog.** Save/Load from the tuning
panel opened a chooser that took *seconds to minutes* to answer a click, while
the app behind it kept animating at a full 60 FPS. It only ever showed up on the
integrated GPU, which turned out to be the clue rather than a coincidence.

`QFileDialog.getSaveFileName` is not a Qt dialog here. Under Cinnamon, Qt loads
the **gtk3 platform theme**, so the chooser is a GTK3 dialog running in-process,
and `QDialog::exec()` ends in `gtk_dialog_run()` — a *nested GLib main loop*.
Qt's posted events are dispatched from inside that loop, so the two 16 ms frame
timers went right on repainting the scene while the dialog was up.

A native-stack profile (`py-spy record --native`) while it was hung:

| inside the dialog's own event loop | before | after |
|---|---|---|
| `sendPostedEvents` → `paintAndFlush` (repainting the shard) | **79%** | 0% |
| `loader_dri3_get_buffers` (Mesa back-buffer wait) | 15% | 0% |
| GDK/GTK event dispatch | **0%** | — |
| idle in `poll` | — | 88% |

So the dialog's input handling was competing with the whole HDR chain for the
main thread and losing. Mesa makes it far worse than NVIDIA: `makeCurrent`
enters `loader_dri3_get_buffers`, which *blocks* in `xcb_wait_for_special_event`
waiting on the X server for a free buffer. The NVIDIA driver never takes that
path, and its frames are cheap enough to leave gaps — hence "only on the iGPU".

The fix is one guard in `ShardWidget.advance()`: skip the repaint while
`QApplication.activeModalWidget()` is set. Animation *time* still advances, so
nothing drifts; only the paint is held back, and the scene resumes on the next
tick. Click latency went from seconds to 116 ms.

**The load-bearing detail:** a native GTK dialog still registers through Qt as
the active modal widget (`QDialog::exec()` runs before handing off to GTK).
That is what makes the guard a fact rather than a guess about what is on top.

**If you add another animation driver, it needs the same guard.** Anything that
calls `update()` on a timer will re-create this, and it will look like a dialog
bug rather than a render-loop bug. A symptom worth recognising: while starved,
queued clicks arrived so late that a second click on **Save…** re-entered
`_save()` and opened a second chooser on top of the first. That stopped
happening once the repaint was held back; it was never a separate bug.

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

## The HDR lighting pipeline — branch `feat/lighting-effects`

The renderer no longer draws to the screen. It draws to a floating-point buffer
and tonemaps once, at the end:

```
  sky ─┐
       ├─► scene: RGBA16F, 4x MSAA ─► blit-resolve ─► scratch[0]: bright-pass
shard ─┘                    │                              │
                            │                              ├─► flare ─► blur x2
                            │                              └─► blur chain x6
                            ▼                                        │
                     composite: scene + glare + flare, then the       │
                     one tonemap, into the widget's framebuffer ◄─────┘
```

Everything upstream of `post_composite.frag` writes **unbounded linear
radiance**. The post chain is **11 draws** (bright 1, flare 1, flare blur 2,
bloom blur 6, composite 1) on top of the scene's own 3. The shader files are
listed in the README's tuning section.

The blur ping-pongs between three half-resolution scratch buffers, not two:
the flare needs the raw bright-pass that the bloom blur would otherwise
overwrite.

### Why it had to change

The tonemap used to sit at the bottom of `shard.frag`, which meant the shard was
tonemapped and the sky behind it was not, and the glass alpha-blended over the
backdrop in *display* space rather than in radiance. That left nowhere for a
brightness control to go. `c / (1 + 0.55c)` reaches 1.0 at radiance 2.22 and
flat-clips beyond, so `light_intensity` erased the highlight's shape a fraction
of the way into its own travel. Measured on the shipped preset:

| `light_intensity` | result |
| --- | --- |
| 1.0 | as tuned |
| 3.0 | face blowing out, warm tint desaturating toward white |
| 6.0 | flat white blob, no shading left |

Raising the shoulder recovered the gradient, but only by dimming the whole
shard. **In one 8-bit pass, "intense" and "shaped" trade directly against each
other** — the buffer cannot hold radiance 20 in a highlight and 0.5 in the body
at the same time. That is the entire argument for the float buffer, and it is
worth re-deriving before anyone is tempted to simplify this back.

### Two behaviours that are emergent, not coded

**The whitening is the tonemap's doing.** Per-channel Reinhard saturates the
strongest channel first, so a hot core converges on white while the dim falloff
keeps the light's tint. There is no blend toward `#ffffff` anywhere, and adding
one would be a regression: it would bleach the penumbra too, which is not what a
bright lamp does. `light_intensity` is therefore a plain scalar multiplier and
`light_color` stays a separate control.

**The lens flare gates itself on intensity.** It is built from the same
bright-pass buffer as the glare, so at a low `light_intensity` nothing clears the
threshold, the source is black, and every term multiplies out to zero. No
separate enable to keep in sync. It also needs no knowledge of the scene: the
bevel specular and the Fresnel rim are already the brightest pixels, so a
luminance threshold finds the "sheer edges" without any edge detection.

`flare_threshold` sits *on top of* `bloom_threshold` because the two want
different sources. Glare is what a bright pixel does to its neighbours, so a
broad lit area glowing at its edges is correct. A flare is the image of the
aperture reproduced per lens element, so its source has to be a small searing
*point* — fed the bloom's buffer, a blown-out facet became a blown-out ghost and
the frame turned to soup. Related: a flare reads far better against a **domed**
front face (`front_bulge` 1.0, `spec_power` ~140) than a flat one, because a flat
facet spreads its specular over the whole surface and ghosts of a blob are blobs.

### Cost, and the one number to tune

Iris Xe, median of 20–60 frames with `glFinish()` per frame, post chain only
(the scene itself is unchanged):

| | 420x620 | 1920x1080 | 3840x2160 |
| --- | --- | --- | --- |
| whole post chain | **0.84 ms** | 2.89 ms | **6.33 ms** |
| — of which blur chain | 0.31 | 1.14 | 1.26 |
| — of which flare | 0.13 | 1.27 | 0.59 |
| — of which composite | 0.18 | 0.72 | 2.09 |
| — of which resolve blit | 0.10 | 1.09 | 2.77 |

4K was **15.3 ms** before the glare chain became adaptive — the entire frame
budget, spent on post, before the scene drew a triangle. Glare and flare are the
output of a wide blur, so their cost scales with resolution while their *content*
does not; `_bloom_divisor()` now halves until the chain is no wider than
`_BLOOM_MAX_WIDTH` (960 px). Small windows keep the full half-resolution chain
and stay crisp.

**`_BLOOM_MAX_WIDTH` is the knob to raise on a discrete GPU.** The 6.33 ms above
is an integrated part sharing system memory bandwidth. The visible consequence
of the cap is that the same params give slightly softer glare on a 4K panel than
on a 1080p one — check this before concluding a preset "looks wrong" on a bigger
monitor.

### Gotchas worth not rediscovering

- **MSAA had to be re-requested.** The `setSamples(4)` in
  `default_surface_format()` applies to the widget's own framebuffer, which the
  scene no longer draws into. `_SCENE_SAMPLES` requests it again on the
  offscreen target. The `[post] targets` line prints what was actually granted
  and says so explicitly if it comes back `0x`.
- **`release()` on an FBO binds framebuffer 0, which is not where a
  `QOpenGLWidget` draws.** It owns its own framebuffer and Qt composites that, so
  the composite pass must bind `defaultFramebufferObject()` by hand. The nebula
  bake already had this trap and its comment now has company.
- **Never sample a texture attached to the bound framebuffer.** The blur
  ping-pongs between scratch buffers for this reason; there are three, not two,
  because the flare needs the raw bright-pass that the bloom blur would
  otherwise overwrite. On some drivers the aliased case silently works right up
  until it does not.
- **FBO textures are not guaranteed a filter mode.** Every buffer here is
  sampled at offsets between texel centres, so `_ensure_targets` sets
  `GL_LINEAR` and `GL_CLAMP_TO_EDGE` explicitly. Left on `NEAREST` the glare
  comes back blocky and crawls as the camera sways.
- **Restore the active texture unit.** The composite binds three; the shard's
  text atlas and the sky's cubemap both expect unit 0 next frame.
- **Saved presets shifted.** The glass now blends in linear radiance rather than
  display space, and the sky is tonemapped where it previously was not, so stars
  read dimmer. `exposure` and `star_brightness` are the recovery knobs. Presets
  written before this branch simply lack the new fields and load at
  `ShardParams` defaults, which is the intended behaviour of `apply_json_dict`.

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

`_autoload()` is a method of the tuning panel (`TuningPanel._autoload` — do not
re-add a line number here, it has rotted twice), and the panel is only
constructed under `NAIVE_TIMER_TUNE=1`. So the promoted look — red
numerals, `star_density=178`, the tuned nebula — is what you get in tune mode,
and a plain `python -m naive_timer` still renders `ShardParams` defaults. That
is probably not the intent of "auto-load default-params.json"; left alone here
because fixing it changes the app's appearance, which is a decision, not a bug
fix.

Without a display **and** without `xvfb-run`, the GL tier of the smoke test
skips itself: Qt's `offscreen` platform has no OpenGL, and constructing a
`QOpenGLWidget` under it *segfaults* rather than raising. Use `xvfb-run` in CI.

## Branches

`main` carries the shard. The glass volume, starfield, shatter sound and colour
controls have all since landed. Active work is on **`feat/lighting-effects`**
(light intensity → HDR pipeline → glare → lens flare → panel scrolling). No PR
has been opened yet.

Next on that branch is the shatter rework in `TODO.md`. The HDR chain is the
enabling piece for it: "make the pieces sparkle intensely" is a per-wedge
specular pulse, which in an 8-bit buffer clips to white and reads flat, and with
this chain becomes glare and streaks that scale with how hot the glint actually
is. `light_intensity` and `flare` on the break are the levers — and unlike the
idle state, there is no readout left to keep legible, so both can go much
further than their defaults.
