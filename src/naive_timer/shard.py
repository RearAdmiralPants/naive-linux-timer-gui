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

# Texture the numerals are drawn into. Wide, because the readout is wide, and
# oversized because the glyphs get magnified across the face of the shard.
_TEX_W, _TEX_H = 1536, 512
_TEX_PT = 192

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

# How far the centre of the shard lifts off the rim. Drives the facet angles,
# and therefore how sharply the highlight breaks between them.
_PEAK_Z = 0.16


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
    font_family: str = "monospace"
    font_bold: bool = True


def default_surface_format() -> QSurfaceFormat:
    """A 3.3 core profile with multisampling. Must be set before QApplication."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    return fmt


def _build_geometry() -> array.array:
    """Fan the outline into flat-shaded facets around a raised centre.

    Interleaved per vertex: pos(3) normal(3) uv(2) pieceDir(3) = 11 floats.
    """
    data = array.array("f")
    apex = (0.0, 0.0, _PEAK_Z)
    n = len(_OUTLINE)

    for i in range(n):
        ax, ay = _OUTLINE[i]
        bx, by = _OUTLINE[(i + 1) % n]
        tri = [apex, (ax, ay, 0.0), (bx, by, 0.0)]

        # Flat normal from the facet's own winding.
        ux, uy, uz = (tri[1][j] - tri[0][j] for j in range(3))
        vx, vy, vz = (tri[2][j] - tri[0][j] for j in range(3))
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        normal = (nx / length, ny / length, nz / length)

        # Outward direction for the fracture: away from the shard's centre.
        cx = (tri[0][0] + tri[1][0] + tri[2][0]) / 3.0
        cy = (tri[0][1] + tri[1][1] + tri[2][1]) / 3.0
        clen = math.hypot(cx, cy) or 1.0
        piece = (cx / clen, cy / clen, 0.25)

        for px, py, pz in tri:
            u = px * 0.5 + 0.5
            v = 1.0 - (py * 0.5 + 0.5)
            data.extend((px, py, pz, *normal, u, v, *piece))

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
    if width > _TEX_W * 0.92:
        font.setPixelSize(int(_TEX_PT * (_TEX_W * 0.92) / width))
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
        self._fracture = 0.0
        self._spin = 0.0
        self._text = ""

        self._program: QOpenGLShaderProgram | None = None
        self._uniforms: dict[str, int] = {}
        self._texture: QOpenGLTexture | None = None
        self._text_dirty = True
        self._shaders_dirty = False

        self._vao = QOpenGLVertexArrayObject()
        self._vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vertex_data = _build_geometry()
        self._vertex_count = len(self._vertex_data) // 11

        self.setMinimumSize(280, 280)

        self._watcher = QFileSystemWatcher(self)
        for name in ("shard.vert", "shard.frag"):
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
        if not active:
            self._fracture = 0.0
            self._alarm_phase = 0.0

    def advance(self, dt: float) -> None:
        if self._alarm:
            # Break apart quickly, then breathe dark red at ~1.5 Hz.
            self._fracture = min(1.0, self._fracture + dt * 1.6)
            self._alarm_phase += dt * 1.5 * 2.0 * math.pi
        else:
            self._spin += dt * (0.55 if self._model.is_running else 0.12)
        self.update()

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
            program.bindAttributeLocation("aPieceDir", 3)
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
                "uCamPos", "uLightPos", "uGlassColor", "uTextColor",
                "uSpecPower", "uSpecStrength", "uFresnel", "uGlow",
                "uEtch", "uBaseAlpha", "uAlarm", "uFracture", "uSpin",
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
        stride = 11 * 4
        for loc, size, offset in (
            (0, 3, 0),
            (1, 3, 3 * 4),
            (2, 2, 6 * 4),
            (3, 3, 8 * 4),
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
        fns.glClearColor(0.05, 0.06, 0.09, 1.0)

        self._vao.create()
        self._vbo.create()
        self._vbo.bind()
        self._vbo.allocate(
            self._vertex_data.tobytes(), len(self._vertex_data) * 4
        )
        self._vbo.release()

        self._load_program()

    def paintGL(self) -> None:  # noqa: N802
        if self._shaders_dirty:
            self._shaders_dirty = False
            self._load_program()
        if self._text_dirty:
            self._upload_text()

        fns = self.context().functions()
        fns.glClear(_GL_COLOR_BUFFER_BIT | _GL_DEPTH_BUFFER_BIT)

        program = self._program
        if program is None or self._texture is None:
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
        self._set("uGlassColor", QVector3D(*p.glass_color))
        self._set("uTextColor", QVector3D(*p.text_color))
        self._set_float("uSpecPower", float(p.spec_power))
        self._set_float("uSpecStrength", float(p.spec_strength))
        self._set_float("uFresnel", float(p.fresnel))
        self._set_float("uGlow", float(p.glow))
        self._set_float("uEtch", float(p.etch))
        self._set_float("uBaseAlpha", float(p.base_alpha))
        self._set_float("uAlarm", float(alarm))
        self._set_float("uFracture", float(self._fracture))
        self._set_float("uSpin", float(self._spin))

        self._vao.bind()
        fns.glDrawArrays(_GL_TRIANGLES, 0, self._vertex_count)
        self._vao.release()
        self._texture.release(0)
        program.release()

    def resizeGL(self, w: int, h: int) -> None:  # noqa: N802
        pass  # projection is rebuilt from the aspect each frame
