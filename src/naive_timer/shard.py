"""OpenGL glass-shard view: the timer text as a texture on an angled facet.

Replaces the old ``SpinnerWidget`` and keeps its interface (``advance``,
``set_alarm``) so it drops into both tabs unchanged. The one addition is
``set_text``, since the numerals now live on the shard rather than in a
``QLabel`` beneath it.

The models stay UI-free: this widget is handed a formatted string and renders
it. Nothing here knows what a stopwatch is.

Shaders live in ``shaders/*.{vert,frag}`` and are **hot-reloaded** on save --
edit, save, watch the running app change. A shader that fails to compile prints
its error and leaves the previous program in place.

Launch with ``NAIVE_TIMER_TUNE=1`` to get live sliders for every uniform.
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QMatrix4x4,
    QPainter,
    QSurfaceFormat,
    QVector2D,
    QVector3D,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

_SHADER_DIR = Path(__file__).parent / "shaders"

# GL enums we need but QOpenGLFunctions does not re-export.
_GL_FLOAT = 0x1406
_GL_TRIANGLES = 0x0004
_GL_DEPTH_TEST = 0x0B71
_GL_BLEND = 0x0BE2
_GL_SRC_ALPHA = 0x0302
_GL_ONE_MINUS_SRC_ALPHA = 0x0303
_GL_COLOR_BUFFER_BIT = 0x4000
_GL_DEPTH_BUFFER_BIT = 0x0100
_GL_CULL_FACE = 0x0B44
_GL_FRONT = 0x0404
_GL_BACK = 0x0405
_GL_FALSE = 0
_GL_TRUE = 1

# Texture the numerals are drawn into. Wide, because the readout is wide, and
# oversized because the glyphs get magnified across the face of the shard.
_TEX_W, _TEX_H = 1536, 512
_TEX_PT = 192

# Fraction of the texture width the numerals are allowed to occupy. The rest
# is transparent margin, which is what the bevel and side walls sample.
_TEXT_FIT = 0.92

# Irregular outline, traced counter-clockwise. Deliberately not symmetric --
# a regular polygon reads as a gem, not as a shard.
_OUTLINE = [
    (-0.95, 0.26),
    (-0.52, 0.88),
    (0.70, 0.64),
    (0.97, -0.30),
    (0.12, -0.92),
    (-0.82, -0.54),
]

# The shard is a solid, not a flat fan. Cross-section through one edge:
#
#            apex                     <- _PEAK_Z, front face peak
#           /    \
#      inset      inset               <- _BEVEL_Z, at _BEVEL_INSET scale
#     /                \
#   rim                rim            <- z = 0, the silhouette edge
#    |                  |             <- side wall, _THICKNESS deep
#   rim                rim            <- z = -_THICKNESS
#     \                /
#      inset      inset               <- back bevel, shallower than the front
#           \    /
#          back apex
#
# The bevel is what actually reads as "glass": it catches a highlight along
# the silhouette, which a zero-thickness polygon can never do.
_PEAK_Z = 0.14
# Depth of the straight middle slab, between the two bevels. Keep this thin:
# the bevels are what read as glass, and a fat middle makes the shard look
# like a slab of plastic.
_THICKNESS = 0.09
_BEVEL_INSET = 0.90
_BEVEL_Z = 0.05
_BACK_BEVEL_Z = 0.03
_BACK_PEAK_Z = 0.05

# Centre of mass of the whole shard.
_CENTER = (0.0, 0.0, -_THICKNESS / 2.0)

# pos(3) normal(3) uv(2) pieceCenter(3) pieceVel(3) pieceAxis(3) cap(1)
_FLOATS_PER_VERTEX = 18

# Triangles per wedge: 1 front face + 2 front bevel + 2 wall + 2 back bevel
# + 1 back face + 8 radial caps (4 per cut plane).
_TRIS_PER_WEDGE = 16

# Radians per second the shard turns while idle. Constant: it does not react
# to the model's running state.
_IDLE_SPIN_RATE = 0.12

# Seconds for the pieces to clear the frame -- measured by rendering the
# sequence and counting non-background pixels, not guessed. The alert runs for
# 120 s, so the shard is gone for most of it; after this we stop drawing.
_SHATTER_CLEAR_S = 5.5


def parse_hex_color(text: str) -> tuple:
    """``"#ff8800"`` or ``"ff8800"`` -> ``(1.0, 0.533, 0.0)``.

    Raises ``ValueError`` on anything else. Shorthand (``#f80``) is accepted
    because people type it.
    """
    value = text.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        raise ValueError(f"expected RRGGBB or RGB, got {text!r}")
    try:
        channels = tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise ValueError(f"{text!r} is not hexadecimal") from None
    return tuple(c / 255.0 for c in channels)


def format_hex_color(rgb) -> str:
    """``(1.0, 0.533, 0.0)`` -> ``"#ff8800"``. Inverse of parse_hex_color."""
    return "#" + "".join(
        f"{max(0, min(255, round(c * 255.0))):02x}" for c in rgb
    )


@dataclass
class ShardParams:
    """Everything the fragment shader can be tuned by."""

    light_x: float = 2.4
    light_y: float = 2.2
    light_z: float = 2.0
    spec_power: float = 48.0
    spec_strength: float = 0.85
    fresnel: float = 0.55
    glow: float = 0.90
    etch: float = 0.0
    base_alpha: float = 0.55
    glass_color: tuple = (0.16, 0.34, 0.52)
    text_color: tuple = (0.75, 0.93, 1.00)
    light_color: tuple = (1.00, 1.00, 1.00)
    font_family: str = "monospace"
    font_bold: bool = True

    # Procedural backdrop.
    nebula: float = 0.55
    nebula_color_a: tuple = (0.10, 0.16, 0.42)
    nebula_color_b: tuple = (0.42, 0.13, 0.34)
    star_density: float = 26.0
    star_brightness: float = 1.0


def default_surface_format() -> QSurfaceFormat:
    """A 3.3 core profile with multisampling. Must be set before QApplication."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    return fmt


# Shrinks the text projection so the numerals stay inside the bevel's inset
# ring instead of spilling onto the chamfer. >1 makes the text smaller; the rim
# then projects outside [0,1] and clamps to the texture's transparent border.
_FACE_UV_SCALE = 1.22


def _face_uv(x: float, y: float) -> tuple:
    """Planar-project a front-face point into the text texture."""
    u = x * 0.5 * _FACE_UV_SCALE + 0.5
    v = 1.0 - (y * 0.5 * _FACE_UV_SCALE + 0.5)
    return (u, v)


# Corner of the text image, which is always transparent. Side walls and the
# back face sample here so no numerals bleed onto them.
_NO_TEXT_UV = (0.002, 0.002)


def _add_triangle(data: array.array, tri, uvs, body, cap: float = 0.0) -> None:
    """Append one flat-shaded triangle, wound counter-clockwise from outside.

    Consistent outward winding is not cosmetic: the two-pass transparency in
    paintGL culls by face orientation to draw back surfaces before front ones.
    Get a triangle backwards and its wall renders in the wrong order.

    ``body`` is the wedge's (centre, velocity, axis), repeated on every vertex.
    Outwardness is judged against that centre -- the wedge's own interior point
    -- and *not* against the shard's centre of mass. The shard's axis lies
    inside both of a wedge's radial cut planes, so a cap triangle's normal is
    very nearly perpendicular to the direction from the shard centre, and the
    sign of that dot product is noise.

    ``cap`` marks the radial cut faces, which are interior surfaces while the
    shard is whole and are discarded by the fragment shader until it breaks.
    """
    ux, uy, uz = (tri[1][j] - tri[0][j] for j in range(3))
    vx, vy, vz = (tri[2][j] - tri[0][j] for j in range(3))
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx

    centre, velocity, axis = body

    # Does the normal point away from the wedge's interior? If not, the
    # triangle is wound backwards: swap two vertices and flip the normal.
    cx = sum(v[0] for v in tri) / 3.0 - centre[0]
    cy = sum(v[1] for v in tri) / 3.0 - centre[1]
    cz = sum(v[2] for v in tri) / 3.0 - centre[2]
    if nx * cx + ny * cy + nz * cz < 0.0:
        tri = [tri[0], tri[2], tri[1]]
        uvs = [uvs[0], uvs[2], uvs[1]]
        nx, ny, nz = -nx, -ny, -nz

    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    normal = (nx / length, ny / length, nz / length)

    for (px, py, pz), (u, v) in zip(tri, uvs):
        data.extend(
            (px, py, pz, *normal, u, v, *centre, *velocity, *axis, cap)
        )


def _hash01(i: int, salt: int) -> float:
    """Deterministic pseudo-random in [0, 1).

    Deliberately not ``random``: the break must look the same on every run, so
    a bad-looking tumble is reproducible and a test can pin the values.
    """
    x = math.sin(i * 12.9898 + salt * 78.233) * 43758.5453
    return x - math.floor(x)


def _wedge_rigid_body(i: int, corners) -> tuple:
    """Pivot, linear velocity and angular velocity for one wedge.

    The pivot is the wedge's own centroid -- that is the whole point. Rotating
    every piece about the *shard's* centre is what produced the pinwheel.
    """
    n = float(len(corners))
    centre = (
        sum(c[0] for c in corners) / n,
        sum(c[1] for c in corners) / n,
        sum(c[2] for c in corners) / n,
    )

    # Drift outward from the axis, with a little scatter so the break is not a
    # symmetric bloom. Negative z: the pieces recede and shrink, as falling
    # glass does. Positive z threw them at the camera, where they ballooned.
    radial = math.hypot(centre[0], centre[1]) or 1.0
    speed = 0.26 + 0.16 * _hash01(i, 1)
    velocity = (
        centre[0] / radial * speed + (_hash01(i, 2) - 0.5) * 0.12,
        centre[1] / radial * speed + (_hash01(i, 3) - 0.5) * 0.12 + 0.14,
        -(0.10 + 0.20 * _hash01(i, 4)),
    )

    # Angular velocity: direction is the axis, magnitude is rad/sec. Keep this
    # slow -- a wedge's far corner is ~1 unit from its pivot, so even 2 rad/s
    # sweeps it across the frame.
    ax = _hash01(i, 5) - 0.5
    ay = _hash01(i, 6) - 0.5
    az = _hash01(i, 7) - 0.5
    alen = math.sqrt(ax * ax + ay * ay + az * az) or 1.0
    rate = 0.7 + 1.2 * _hash01(i, 8)
    axis = (ax / alen * rate, ay / alen * rate, az / alen * rate)

    return centre, velocity, axis


def _build_geometry() -> array.array:
    """Extrude the outline into a solid, one wedge per edge.

    Each wedge contributes a front face, a front bevel, a side wall, a back
    bevel and a back face -- and all of them share one rigid-body state. That
    makes a wedge a real chunk: the whole solid piece tumbles together, rather
    than the front skin peeling off its own side wall.

    Interleaved per vertex:
        pos(3) normal(3) uv(2) pieceCenter(3) pieceVel(3) pieceAxis(3) = 17
    """
    data = array.array("f")
    front_apex = (0.0, 0.0, _PEAK_Z)
    back_apex = (0.0, 0.0, -_THICKNESS - _BACK_PEAK_Z)
    n = len(_OUTLINE)

    for i in range(n):
        ax, ay = _OUTLINE[i]
        bx, by = _OUTLINE[(i + 1) % n]

        rim_a = (ax, ay, 0.0)
        rim_b = (bx, by, 0.0)
        inset_a = (ax * _BEVEL_INSET, ay * _BEVEL_INSET, _BEVEL_Z)
        inset_b = (bx * _BEVEL_INSET, by * _BEVEL_INSET, _BEVEL_Z)

        back_rim_a = (ax, ay, -_THICKNESS)
        back_rim_b = (bx, by, -_THICKNESS)
        back_inset_a = (
            ax * _BEVEL_INSET, ay * _BEVEL_INSET, -_THICKNESS - _BACK_BEVEL_Z
        )
        back_inset_b = (
            bx * _BEVEL_INSET, by * _BEVEL_INSET, -_THICKNESS - _BACK_BEVEL_Z
        )

        # One rigid body for the whole wedge, pivoting on its own centroid.
        # Built first: its centre is the interior reference _add_triangle uses
        # to orient every facet of this wedge outward.
        piece = _wedge_rigid_body(
            i,
            [
                rim_a, rim_b, inset_a, inset_b,
                back_rim_a, back_rim_b, back_inset_a, back_inset_b,
                front_apex, back_apex,
            ],
        )

        uv_apex = _face_uv(0.0, 0.0)
        uv_inset_a = _face_uv(inset_a[0], inset_a[1])
        uv_inset_b = _face_uv(inset_b[0], inset_b[1])
        uv_rim_a = _face_uv(ax, ay)
        uv_rim_b = _face_uv(bx, by)
        blank = [_NO_TEXT_UV] * 3

        # Front face: carries the numerals.
        _add_triangle(
            data, [front_apex, inset_a, inset_b],
            [uv_apex, uv_inset_a, uv_inset_b], piece,
        )
        # Front bevel: the chamfer that catches the edge highlight.
        _add_triangle(
            data, [inset_a, rim_a, rim_b],
            [uv_inset_a, uv_rim_a, uv_rim_b], piece,
        )
        _add_triangle(
            data, [inset_a, rim_b, inset_b],
            [uv_inset_a, uv_rim_b, uv_inset_b], piece,
        )
        # Side wall: the thickness you can actually see.
        _add_triangle(data, [rim_a, back_rim_a, back_rim_b], blank, piece)
        _add_triangle(data, [rim_a, back_rim_b, rim_b], blank, piece)
        # Back bevel, shallower than the front.
        _add_triangle(
            data, [back_rim_a, back_inset_a, back_inset_b], blank, piece
        )
        _add_triangle(data, [back_rim_a, back_inset_b, back_rim_b], blank, piece)
        # Back face.
        _add_triangle(data, [back_apex, back_inset_b, back_inset_a], blank, piece)

        # Radial cut faces. Without these a wedge is an open shell, and the
        # tumbling pieces read as hollow the moment they turn edge-on. Each
        # cut is a hexagon in the plane through the shard's axis and one rim
        # point; fan it from the front apex.
        for profile in (
            [front_apex, inset_a, rim_a, back_rim_a, back_inset_a, back_apex],
            [front_apex, inset_b, rim_b, back_rim_b, back_inset_b, back_apex],
        ):
            for k in range(1, len(profile) - 1):
                _add_triangle(
                    data,
                    [profile[0], profile[k], profile[k + 1]],
                    blank,
                    piece,
                    cap=1.0,
                )

    return data


def render_text_image(text: str, params: ShardParams) -> QImage:
    """Draw the numerals into an RGBA image. No GL context required.

    Kept a free function rather than a widget method so it can be unit-tested
    without a GL context -- the ``offscreen`` Qt platform has no GL at all.
    """
    image = QImage(_TEX_W, _TEX_H, QImage.Format_RGBA8888)
    image.fill(Qt.transparent)
    if not text:
        return image

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)

    font = QFont(params.font_family)
    font.setBold(params.font_bold)
    font.setPixelSize(_TEX_PT)
    painter.setFont(font)

    # Shrink to fit rather than clip: the readout widens by a character once
    # the hour rolls over.
    width = painter.fontMetrics().horizontalAdvance(text)
    if width > _TEX_W * _TEXT_FIT:
        font.setPixelSize(int(_TEX_PT * (_TEX_W * _TEXT_FIT) / width))
        painter.setFont(font)

    # White; the shader tints by uTextColor so colour stays a live uniform.
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(image.rect(), Qt.AlignCenter, text)
    painter.end()
    return image


class ShardWidget(QOpenGLWidget):
    """Drop-in replacement for SpinnerWidget, plus ``set_text``."""

    def __init__(self, model, params: ShardParams | None = None) -> None:
        super().__init__()
        self._model = model
        self.params = params or ShardParams()

        self._alarm = False
        self._alarm_phase = 0.0
        self._shatter_t = 0.0  # seconds since the break; 0 while intact
        self._spin = 0.0
        self._spin_at_break = 0.0
        self._text = ""

        self._program: QOpenGLShaderProgram | None = None
        self._uniforms: dict[str, int] = {}
        self._sky_program: QOpenGLShaderProgram | None = None
        self._sky_uniforms: dict[str, int] = {}
        self._sky_vao = QOpenGLVertexArrayObject()
        self._elapsed = 0.0
        self._texture: QOpenGLTexture | None = None
        self._text_dirty = True
        self._shaders_dirty = False

        self._vao = QOpenGLVertexArrayObject()
        self._vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vertex_data = _build_geometry()
        self._vertex_count = len(self._vertex_data) // _FLOATS_PER_VERTEX

        self.setMinimumSize(280, 280)

        self._watcher = QFileSystemWatcher(self)
        for name in ("shard.vert", "shard.frag", "sky.vert", "sky.frag"):
            self._watcher.addPath(str(_SHADER_DIR / name))
        self._watcher.fileChanged.connect(self._on_shader_changed)

    # -- public interface, mirrors the old spinner ------------------------

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self._text_dirty = True

    def set_alarm(self, active: bool) -> None:
        if active == self._alarm:
            return
        self._alarm = active
        if active:
            # Break from wherever the idle rotation happens to be, not from
            # the rest pose. Otherwise the shard visibly snaps back to its
            # start angle on the frame it shatters.
            self._spin_at_break = self._spin
        else:
            # Reset reassembles the shard.
            self._shatter_t = 0.0
            self._alarm_phase = 0.0

    def advance(self, dt: float) -> None:
        # The sky drifts and twinkles in every state, including after the
        # shard has shattered and stopped being drawn.
        self._elapsed += dt

        if self._alarm:
            # The pieces tumble away and keep going; the red pulse continues
            # long after they have left the frame, until the user resets.
            self._shatter_t += dt
            self._alarm_phase += dt * 1.5 * 2.0 * math.pi
        else:
            # One idle speed, whether or not the model is running. Speeding up
            # while the timer ran drew the eye to the rotation instead of the
            # numerals.
            self._spin += dt * _IDLE_SPIN_RATE
        self.update()

    @property
    def pieces_have_cleared(self) -> bool:
        """True once the tumbling wedges are off screen."""
        return self._shatter_t > _SHATTER_CLEAR_S

    def refresh_params(self) -> None:
        """Call after mutating ``params`` from the tuning panel."""
        self._text_dirty = True  # font/colour may have changed
        self.update()

    # -- shader loading ---------------------------------------------------

    def _on_shader_changed(self, path: str) -> None:
        # Editors often replace rather than modify; re-add to keep watching.
        if path not in self._watcher.files():
            self._watcher.addPath(path)
        self._shaders_dirty = True
        self.update()

    def _load_program(self) -> None:
        """Compile the shader pair. Keep the old program if this fails."""
        program = QOpenGLShaderProgram()
        ok = program.addShaderFromSourceFile(
            QOpenGLShader.Vertex, str(_SHADER_DIR / "shard.vert")
        ) and program.addShaderFromSourceFile(
            QOpenGLShader.Fragment, str(_SHADER_DIR / "shard.frag")
        )
        if ok:
            program.bindAttributeLocation("aPos", 0)
            program.bindAttributeLocation("aNormal", 1)
            program.bindAttributeLocation("aUV", 2)
            program.bindAttributeLocation("aPieceCenter", 3)
            program.bindAttributeLocation("aPieceVel", 4)
            program.bindAttributeLocation("aPieceAxis", 5)
            program.bindAttributeLocation("aCap", 6)
            ok = program.link()

        if not ok:
            log = program.log().strip()
            if self._program is None:
                raise RuntimeError(f"initial shader compile failed:\n{log}")
            print(f"[shard] shader reload failed, keeping previous:\n{log}")
            return

        self._program = program
        # Cache uniform locations: PySide6's setUniformValue only accepts a
        # name as bytes, and only the int-location overloads cover plain
        # floats. Looking them up once is both correct and cheaper.
        program.bind()
        self._uniforms = {
            name: program.uniformLocation(name)
            for name in (
                "uText", "uModel", "uView", "uProj", "uNormalMat",
                "uCamPos", "uLightPos", "uLightColor", "uGlassColor",
                "uTextColor",
                "uSpecPower", "uSpecStrength", "uFresnel", "uGlow",
                "uEtch", "uBaseAlpha", "uAlarm", "uShatterT", "uSpin",
                "uSpinAtBreak",
            )
        }
        program.release()
        self._bind_attributes()
        print("[shard] shaders reloaded")

    def _set(self, name: str, value) -> None:
        """Set a uniform by name, skipping ones the compiler optimised out."""
        location = self._uniforms.get(name, -1)
        if location >= 0:
            self._program.setUniformValue(location, value)

    def _load_sky_program(self) -> None:
        """Compile the backdrop shaders. Keep the old program if this fails."""
        program = QOpenGLShaderProgram()
        ok = program.addShaderFromSourceFile(
            QOpenGLShader.Vertex, str(_SHADER_DIR / "sky.vert")
        ) and program.addShaderFromSourceFile(
            QOpenGLShader.Fragment, str(_SHADER_DIR / "sky.frag")
        )
        if ok:
            ok = program.link()

        if not ok:
            log = program.log().strip()
            if self._sky_program is None:
                raise RuntimeError(f"initial sky shader compile failed:\n{log}")
            print(f"[sky] shader reload failed, keeping previous:\n{log}")
            return

        program.bind()
        self._sky_uniforms = {
            name: program.uniformLocation(name)
            for name in (
                "uResolution", "uTime", "uNebula", "uNebulaColorA",
                "uNebulaColorB", "uStarDensity", "uStarBrightness",
            )
        }
        program.release()
        self._sky_program = program
        print("[sky] shaders reloaded")

    def _draw_sky(self, fns) -> None:
        """Fullscreen backdrop. No depth, no blending, no vertex buffer."""
        program = self._sky_program
        if program is None:
            return

        p = self.params
        fns.glDisable(_GL_DEPTH_TEST)
        fns.glDisable(_GL_BLEND)
        fns.glDepthMask(_GL_FALSE)

        program.bind()
        for name, value in (
            ("uTime", float(self._elapsed)),
            ("uNebula", float(p.nebula)),
            ("uStarDensity", float(p.star_density)),
            ("uStarBrightness", float(p.star_brightness)),
        ):
            loc = self._sky_uniforms.get(name, -1)
            if loc >= 0:
                program.setUniformValue1f(loc, value)
        for name, value in (
            ("uResolution", QVector2D(float(self.width()), float(self.height()))),
            ("uNebulaColorA", QVector3D(*p.nebula_color_a)),
            ("uNebulaColorB", QVector3D(*p.nebula_color_b)),
        ):
            loc = self._sky_uniforms.get(name, -1)
            if loc >= 0:
                program.setUniformValue(loc, value)

        self._sky_vao.bind()
        fns.glDrawArrays(_GL_TRIANGLES, 0, 3)
        self._sky_vao.release()
        program.release()

        fns.glDepthMask(_GL_TRUE)
        fns.glEnable(_GL_DEPTH_TEST)
        fns.glEnable(_GL_BLEND)

    def _set_float(self, name: str, value: float) -> None:
        """Set a float uniform.

        Not the same as ``_set``: PySide6 lists setUniformValue's int overload
        before its float one, so a Python float binds to the int overload and
        silently truncates -- 0.55 arrives in the shader as 0. That zeroed the
        alpha and the whole shard rendered invisible. setUniformValue1f is
        unambiguous.
        """
        location = self._uniforms.get(name, -1)
        if location >= 0:
            self._program.setUniformValue1f(location, value)

    def _bind_attributes(self) -> None:
        assert self._program is not None
        self._vao.bind()
        self._vbo.bind()
        stride = _FLOATS_PER_VERTEX * 4
        for loc, size, offset in (
            (0, 3, 0),        # aPos
            (1, 3, 3 * 4),    # aNormal
            (2, 2, 6 * 4),    # aUV
            (3, 3, 8 * 4),    # aPieceCenter
            (4, 3, 11 * 4),   # aPieceVel
            (5, 3, 14 * 4),   # aPieceAxis
            (6, 1, 17 * 4),   # aCap
        ):
            self._program.enableAttributeArray(loc)
            self._program.setAttributeBuffer(loc, _GL_FLOAT, offset, size, stride)
        self._vbo.release()
        self._vao.release()

    # -- text texture -----------------------------------------------------

    def _upload_text(self) -> None:
        if self._texture is not None:
            self._texture.destroy()
        # No .mirrored() here: the UV mapping already puts v=0 at the top of
        # the shard, which is where QOpenGLTexture puts the QImage's first row.
        self._texture = QOpenGLTexture(render_text_image(self._text, self.params))
        # Sample the base level: the glyphs are minified onto the face, so
        # mipmapping picks a blurry level and the numerals go soft. Anisotropy
        # keeps them crisp at the shard's oblique angle.
        self._texture.setMinificationFilter(QOpenGLTexture.Linear)
        self._texture.setMagnificationFilter(QOpenGLTexture.Linear)
        self._texture.setMaximumAnisotropy(16.0)
        self._texture.setWrapMode(QOpenGLTexture.ClampToEdge)
        self._text_dirty = False

    # -- QOpenGLWidget ----------------------------------------------------

    def initializeGL(self) -> None:  # noqa: N802 (Qt naming)
        fns = self.context().functions()
        fns.glEnable(_GL_DEPTH_TEST)
        fns.glEnable(_GL_BLEND)
        fns.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA)
        # Black, not a dark blue-grey. The sky pass covers every pixel, so this
        # is only ever seen if the backdrop fails to draw -- and it should look
        # unmistakably broken when that happens, not like a slightly dim sky.
        fns.glClearColor(0.0, 0.0, 0.0, 1.0)

        self._vao.create()
        self._vbo.create()
        self._vbo.bind()
        self._vbo.allocate(
            self._vertex_data.tobytes(), len(self._vertex_data) * 4
        )
        self._vbo.release()

        # Core profile requires a bound VAO for any draw, even one that fetches
        # no attributes. The sky triangle builds itself from gl_VertexID.
        self._sky_vao.create()

        self._load_program()
        self._load_sky_program()

    def paintGL(self) -> None:  # noqa: N802
        if self._shaders_dirty:
            self._shaders_dirty = False
            self._load_program()
            self._load_sky_program()
        if self._text_dirty:
            self._upload_text()

        fns = self.context().functions()
        fns.glClear(_GL_COLOR_BUFFER_BIT | _GL_DEPTH_BUFFER_BIT)

        # Backdrop first, and unconditionally: the shard may be gone, but the
        # sky is still there.
        self._draw_sky(fns)

        program = self._program
        if program is None or self._texture is None:
            return

        # The wedges have tumbled out of frame. The alert still has ~115 s to
        # run; there is nothing left of the shard to rasterise.
        if self.pieces_have_cleared:
            return

        p = self.params
        aspect = max(self.width(), 1) / max(self.height(), 1)

        model = QMatrix4x4()
        model.rotate(-16.0, 1.0, 0.0, 0.0)
        model.rotate(-22.0, 0.0, 1.0, 0.0)

        view = QMatrix4x4()
        cam = QVector3D(0.0, 0.0, 3.2)
        view.lookAt(cam, QVector3D(0, 0, 0), QVector3D(0, 1, 0))

        proj = QMatrix4x4()
        proj.perspective(38.0, aspect, 0.1, 100.0)

        alarm = 0.0
        if self._alarm:
            alarm = 0.5 + 0.5 * math.sin(self._alarm_phase)

        program.bind()
        self._texture.bind(0)
        self._set("uText", 0)
        self._set("uModel", model)
        self._set("uView", view)
        self._set("uProj", proj)
        self._set("uNormalMat", model.normalMatrix())
        self._set("uCamPos", cam)
        self._set("uLightPos", QVector3D(p.light_x, p.light_y, p.light_z))
        self._set("uLightColor", QVector3D(*p.light_color))
        self._set("uGlassColor", QVector3D(*p.glass_color))
        self._set("uTextColor", QVector3D(*p.text_color))
        self._set_float("uSpecPower", float(p.spec_power))
        self._set_float("uSpecStrength", float(p.spec_strength))
        self._set_float("uFresnel", float(p.fresnel))
        self._set_float("uGlow", float(p.glow))
        self._set_float("uEtch", float(p.etch))
        self._set_float("uBaseAlpha", float(p.base_alpha))
        self._set_float("uAlarm", float(alarm))
        self._set_float("uShatterT", float(self._shatter_t))
        self._set_float("uSpin", float(self._spin))
        self._set_float("uSpinAtBreak", float(self._spin_at_break))

        # Two passes, back surfaces first. The shard is translucent, so blend
        # order matters: draw the inside of the solid, then the outside over
        # it. Culling by winding gives that ordering for free, with no
        # per-triangle depth sort. Depth *writes* stay on so the numerals on
        # the front face still occlude the far wall behind them.
        self._vao.bind()
        fns.glEnable(_GL_CULL_FACE)
        for cull in (_GL_FRONT, _GL_BACK):
            fns.glCullFace(cull)
            fns.glDrawArrays(_GL_TRIANGLES, 0, self._vertex_count)
        fns.glDisable(_GL_CULL_FACE)
        self._vao.release()
        self._texture.release(0)
        program.release()

    def resizeGL(self, w: int, h: int) -> None:  # noqa: N802
        pass  # projection is rebuilt from the aspect each frame
