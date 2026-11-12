"""Drifting dust clouds, simulated and drawn entirely on the GPU.

Division of labour:

* **CPU (this file)** owns a handful of *clouds*: centre, drift velocity,
  radius, albedo, scattering anisotropy, tint. Moving a dozen points per frame
  is trivial, and it is where the decisions live (spawn, respawn, later the
  eddies' capture and release).
* **GPU** owns every *particle*. ``dust_step.comp`` steps them in an SSBO and
  ``dust.vert`` draws sprites straight out of the same buffer, so particle data
  never crosses the bus in either direction.

The only per-frame upload is the cloud table (``_CLOUD_FLOATS`` floats each).
A respawn is signalled by bumping the cloud's *generation*; particles notice
the mismatch on their next step and re-seed themselves. No per-particle work
ever happens in Python.

Needs OpenGL 4.3 (compute + SSBOs). Every GPU this project targets -- Intel and
AMD via Mesa, NVIDIA -- reports 4.6; llvmpipe under Xvfb reports 4.5. On
anything older ``available`` stays False and the field draws nothing rather
than taking the app down.
"""

from __future__ import annotations

import random
import struct
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram

_SHADER_DIR = Path(__file__).parent / "shaders"
SHADER_FILES = ("dust_step.comp", "dust.vert", "dust.frag")

_GL_TRIANGLES = 0x0004
_GL_BLEND = 0x0BE2
_GL_DEPTH_TEST = 0x0B71
_GL_FALSE = 0
_GL_TRUE = 1
_GL_ONE = 1
_GL_SRC_ALPHA = 0x0302
_GL_ONE_MINUS_SRC_ALPHA = 0x0303
_GL_SHADER_STORAGE_BUFFER = 0x90D2
_GL_SHADER_STORAGE_BARRIER_BIT = 0x2000

_LOCAL_SIZE = 128          # must match dust_step.comp
_PARTICLE_FLOATS = 8       # vec4 pos + vec4 vel
_CLOUD_FLOATS = 20         # five vec4s, see Cloud in the shaders
MAX_CLOUDS = 24

# The fixed simulation step. Variable frame times are absorbed by running a
# whole number of these, so the springs behave the same at 30 and 144 fps.
_STEP_S = 1.0 / 60.0
# Live frames may run at most this many steps; anything beyond is dropped, so
# a stall (a modal dialog, a suspended laptop) does not replay minutes of sim.
_MAX_LIVE_STEPS = 6

# The volume clouds live in. The camera sits ~3 units out on +z looking at the
# origin, so this reaches well behind the shard and a little in front of it.
# X is the drift axis: clouds enter at one side and leave at the other.
BOUNDS_X = 7.5
BOUNDS_Y = 4.0
BOUNDS_Z = (-9.0, 1.8)
# How long a freshly spawned cloud takes to fade in. Spawns happen off-frame,
# but the first population at startup does not.
_FADE_IN_S = 2.5


@dataclass
class Cloud:
    center: list
    vel: tuple
    radius: float
    albedo: float
    aniso: float
    color: tuple
    fraction: float      # share of the cloud's particle slots in use ("volume")
    opacity: float
    seed: int
    swirl: float
    generation: int = 1
    age: float = 0.0

    def pack(self) -> list:
        fade = min(1.0, self.age / _FADE_IN_S)
        return [
            *self.center, self.radius,
            *self.vel, float(self.generation),
            *self.color, self.albedo,
            self.aniso, self.fraction, self.opacity, float(self.seed),
            fade, self.swirl, 0.0, 0.0,
        ]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _span(rng: random.Random, lo: float, hi: float) -> float:
    lo, hi = min(lo, hi), max(lo, hi)
    return rng.uniform(lo, hi)


def spawn_cloud(rng: random.Random, params, *, anywhere: bool,
                generation: int = 1) -> Cloud:
    """A new cloud with every per-cloud property drawn from params' ranges.

    ``anywhere`` scatters it through the whole volume (the initial population,
    so the first frame is not empty); otherwise it enters at the upwind edge.
    """
    speed = _span(rng, params.dust_speed_min, params.dust_speed_max)
    heading = rng.choice((-1.0, 1.0))
    vel = (
        heading * speed,
        rng.uniform(-0.25, 0.25) * speed,
        rng.uniform(-0.3, 0.3) * speed,
    )
    radius = _span(rng, params.dust_size_min, params.dust_size_max)
    if anywhere:
        x = rng.uniform(-BOUNDS_X, BOUNDS_X)
    else:
        x = -heading * (BOUNDS_X + radius)
    center = [
        x,
        rng.uniform(-BOUNDS_Y, BOUNDS_Y) * 0.8,
        rng.uniform(*BOUNDS_Z),
    ]
    mix = rng.random()
    color = tuple(
        _lerp(a, b, mix) for a, b in zip(params.dust_color_a, params.dust_color_b)
    )
    return Cloud(
        center=center,
        vel=vel,
        radius=radius,
        albedo=_span(rng, params.dust_albedo_min, params.dust_albedo_max),
        aniso=_span(rng, params.dust_aniso_min, params.dust_aniso_max),
        color=color,
        fraction=_span(rng, params.dust_volume_min, params.dust_volume_max),
        opacity=rng.uniform(0.6, 1.4),
        seed=rng.randrange(1, 1 << 20),
        swirl=rng.uniform(0.4, 1.0) * params.dust_swirl * rng.choice((-1.0, 1.0)),
        generation=generation,
        age=_FADE_IN_S if not anywhere else 0.0,
    )


def out_of_bounds(c: Cloud) -> bool:
    x, y, z = c.center
    r = c.radius
    return (
        abs(x) > BOUNDS_X + r * 1.5
        or abs(y) > BOUNDS_Y + r * 1.5
        or not (BOUNDS_Z[0] - r * 1.5 <= z <= BOUNDS_Z[1] + r * 1.5)
    )


@dataclass
class CloudSet:
    """The CPU side of the field, free of GL so it can be tested headlessly."""

    seed: int = 1
    clouds: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        # One counter for the whole set, never reused. Particle slots outlive
        # the cloud in them (a count change re-fills slot i with a different
        # cloud), and a per-cloud counter would hand the newcomer a generation
        # the stale particles already match -- so they would never re-seed.
        self._generation = 0

    def _next_generation(self) -> int:
        self._generation += 1
        return self._generation

    def sync_count(self, params) -> None:
        want = max(0, min(MAX_CLOUDS, int(round(params.dust_clouds))))
        while len(self.clouds) < want:
            self.clouds.append(spawn_cloud(
                self._rng, params, anywhere=True,
                generation=self._next_generation(),
            ))
        del self.clouds[want:]

    def step(self, dt: float, params) -> None:
        self.sync_count(params)
        for i, c in enumerate(self.clouds):
            c.age += dt
            for k in range(3):
                c.center[k] += c.vel[k] * dt
            if out_of_bounds(c):
                self.clouds[i] = spawn_cloud(
                    self._rng, params, anywhere=False,
                    generation=self._next_generation(),
                )

    def pack(self) -> bytes:
        floats = []
        for c in self.clouds:
            floats.extend(c.pack())
        if not floats:  # an SSBO binding of size 0 is an error on some drivers
            floats = [0.0] * _CLOUD_FLOATS
        return struct.pack(f"{len(floats)}f", *floats)


class DustField:
    """GL owner for the dust. Create in initializeGL, call from paintGL."""

    def __init__(self, seed: int = 1) -> None:
        self.available = False
        self.error = ""
        self.clouds = CloudSet(seed=seed)
        self._pending = 0.0
        self._unbounded = False
        self._time = 0.0
        self._step_prog: QOpenGLShaderProgram | None = None
        self._draw_prog: QOpenGLShaderProgram | None = None
        self._particles: QOpenGLBuffer | None = None
        self._cloud_buf: QOpenGLBuffer | None = None
        self._per_cloud = 0
        self._shaders_dirty = False

    # -- lifecycle ---------------------------------------------------------

    def initialize(self, ctx) -> None:
        fmt = ctx.format()
        version = (fmt.majorVersion(), fmt.minorVersion())
        if version < (4, 3):
            self.error = f"needs OpenGL 4.3, context is {version[0]}.{version[1]}"
            print(f"[dust] disabled: {self.error}")
            return
        self._particles = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._particles.create()
        self._cloud_buf = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._cloud_buf.create()
        self._cloud_buf.setUsagePattern(QOpenGLBuffer.StreamDraw)
        self.available = self._load_programs()

    def mark_shaders_dirty(self) -> None:
        self._shaders_dirty = True

    def _load_programs(self) -> bool:
        step = QOpenGLShaderProgram()
        ok = step.addShaderFromSourceFile(
            QOpenGLShader.Compute, str(_SHADER_DIR / "dust_step.comp")
        ) and step.link()
        draw = QOpenGLShaderProgram()
        ok = ok and draw.addShaderFromSourceFile(
            QOpenGLShader.Vertex, str(_SHADER_DIR / "dust.vert")
        ) and draw.addShaderFromSourceFile(
            QOpenGLShader.Fragment, str(_SHADER_DIR / "dust.frag")
        ) and draw.link()
        if not ok:
            # Keep the previous programs on a bad hot-reload edit.
            self.error = (step.log() + draw.log()).strip()
            print(f"[dust] shader error:\n{self.error}")
            return self._step_prog is not None
        self._step_prog, self._draw_prog = step, draw
        print("[dust] shaders reloaded")
        return True

    def _ensure_particles(self, per_cloud: int) -> None:
        if per_cloud == self._per_cloud:
            return
        self._per_cloud = per_cloud
        count = per_cloud * MAX_CLOUDS
        # Zeroed generations (pos.w == 0) never match a live cloud (>= 1), so
        # every particle seeds itself on the first step.
        zeros = bytes(count * _PARTICLE_FLOATS * 4)
        self._particles.bind()
        self._particles.allocate(zeros, len(zeros))
        self._particles.release()
        print(f"[dust] {count} particle slots ({per_cloud} per cloud)")

    # -- per frame ---------------------------------------------------------

    def advance(self, dt: float) -> None:
        """Bank animation time; it is spent in fixed steps at the next render."""
        self._pending += dt

    def simulate(self, seconds: float) -> None:
        """Bank time *without* the live step cap -- for stills and tests."""
        self._pending += seconds
        self._unbounded = True

    def render(self, fns, ef, vao, params, camera, aspect: float,
               fov_degrees: float) -> None:
        if not params.dust_enabled:
            self._pending = 0.0
            return
        if self._shaders_dirty:
            self._shaders_dirty = False
            self.available = self._load_programs() or self.available
        if not self.available:
            return

        per_cloud = max(_LOCAL_SIZE, int(params.dust_particles) // _LOCAL_SIZE * _LOCAL_SIZE)
        self._ensure_particles(per_cloud)

        steps = int(self._pending / _STEP_S)
        if not self._unbounded:
            steps = min(steps, _MAX_LIVE_STEPS)
            self._pending = min(self._pending - steps * _STEP_S, _STEP_S)
        else:
            self._pending -= steps * _STEP_S
            self._unbounded = False

        ef.glBindBufferBase(_GL_SHADER_STORAGE_BUFFER, 0, self._particles.bufferId())
        ef.glBindBufferBase(_GL_SHADER_STORAGE_BUFFER, 1, self._cloud_buf.bufferId())

        groups = per_cloud * MAX_CLOUDS // _LOCAL_SIZE
        prog = self._step_prog
        for _ in range(steps):
            self.clouds.step(_STEP_S, params)
            self._time += _STEP_S
            self._upload_clouds()
            prog.bind()
            for name, value in (
                ("uDt", _STEP_S), ("uTime", self._time),
                ("uCohesion", params.dust_cohesion), ("uDrag", params.dust_drag),
                ("uTurbulence", params.dust_turbulence),
            ):
                prog.setUniformValue1f(prog.uniformLocation(name), float(value))
            prog.setUniformValue1i(prog.uniformLocation("uPerCloud"), per_cloud)
            prog.setUniformValue1i(prog.uniformLocation("uCloudCount"),
                                   len(self.clouds.clouds))
            ef.glDispatchCompute(groups, 1, 1)
            ef.glMemoryBarrier(_GL_SHADER_STORAGE_BARRIER_BIT)
        if steps == 0:
            self._upload_clouds()  # a count change must still reach the draw
        if not self.clouds.clouds:
            return

        self._draw(fns, vao, params, camera, aspect, fov_degrees, per_cloud)

    def _upload_clouds(self) -> None:
        data = self.clouds.pack()
        self._cloud_buf.bind()
        self._cloud_buf.allocate(data, len(data))
        self._cloud_buf.release()

    def _draw(self, fns, vao, params, camera, aspect, fov_degrees, per_cloud) -> None:
        eye, right, up, _forward = camera
        view = QMatrix4x4()
        view.lookAt(eye, QVector3D(0, 0, 0), QVector3D(0, 1, 0))
        proj = QMatrix4x4()
        proj.perspective(fov_degrees, aspect, 0.1, 100.0)

        prog = self._draw_prog
        prog.bind()
        loc = prog.uniformLocation
        prog.setUniformValue(loc("uViewProj"), proj * view)
        prog.setUniformValue(loc("uCamPos"), eye)
        prog.setUniformValue(loc("uCamRight"), right)
        prog.setUniformValue(loc("uCamUp"), up)
        prog.setUniformValue(loc("uLightPos"),
                             QVector3D(params.light_x, params.light_y, params.light_z))
        prog.setUniformValue(loc("uLightColor"), QVector3D(*params.light_color))
        for name, value in (
            ("uLightIntensity", params.light_intensity),
            ("uGrain", params.dust_grain),
            ("uOpacity", params.dust_opacity),
            ("uBrightness", params.dust_brightness),
            ("uAmbient", params.dust_ambient),
        ):
            prog.setUniformValue1f(loc(name), float(value))
        prog.setUniformValue1i(loc("uPerCloud"), per_cloud)
        prog.setUniformValue1i(loc("uCloudCount"), len(self.clouds.clouds))

        # Premultiplied "over": see dust.vert for why this, not additive. No
        # depth: the sky writes none, and the shard is drawn after the dust.
        fns.glDisable(_GL_DEPTH_TEST)
        fns.glDepthMask(_GL_FALSE)
        fns.glEnable(_GL_BLEND)
        fns.glBlendFunc(_GL_ONE, _GL_ONE_MINUS_SRC_ALPHA)
        vao.bind()
        fns.glDrawArrays(_GL_TRIANGLES, 0, 6 * per_cloud * len(self.clouds.clouds))
        vao.release()
        fns.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA)
        fns.glDepthMask(_GL_TRUE)
        fns.glEnable(_GL_DEPTH_TEST)
        prog.release()
