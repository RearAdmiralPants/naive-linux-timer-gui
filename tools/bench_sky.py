"""Time the real sky.frag at a given resolution, offscreen.

The sky is the app's dominant per-pixel cost: two 5-octave 3D fbm calls plus
three star layers, evaluated for every pixel of every frame. It is therefore
the thing that decides whether a given GPU can hold the 16 ms frame budget.

Renders FRAMES frames into an FBO with glFinish() on each, so the number is
GPU work rather than queue-submit latency. uTime advances per frame so the
driver cannot hoist anything out of the loop.

    python tools/bench_sky.py [WIDTH HEIGHT [FRAMES]]

With no arguments it uses the primary display's resolution. Note this measures
the shader in isolation: it excludes the shard, and it excludes PRIME's
per-frame copy back to the display, which a windowed app does pay.
"""
import math
import pathlib
import subprocess
import sys
import time

from PySide6.QtCore import QSize
from PySide6.QtGui import (
    QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat, QVector3D,
)
from PySide6.QtOpenGL import (
    QOpenGLFramebufferObject, QOpenGLShader, QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)

from naive_timer.shard import ShardParams, _FOV_DEGREES

GL_TRIANGLES = 0x0004
GL_RENDERER = 0x1F01

SHADERS = pathlib.Path(__file__).resolve().parent.parent / "src" / "naive_timer" / "shaders"


def primary_resolution(fallback=(1920, 1080)):
    """Ask xrandr for the current mode of the primary display."""
    try:
        out = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return fallback
    for line in out.splitlines():
        if "*" in line:
            w, _, h = line.split()[0].partition("x")
            return int(w), int(h)
    return fallback


def main(argv):
    if len(argv) >= 3:
        width, height = int(argv[1]), int(argv[2])
    else:
        width, height = primary_resolution()
    frames = int(argv[3]) if len(argv) >= 4 else 60

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QGuiApplication(argv)  # noqa: F841  (must outlive the GL objects)

    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()

    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        return "could not create an OpenGL context"
    ctx.makeCurrent(surface)
    gl = ctx.functions()

    prog = QOpenGLShaderProgram()
    prog.addShaderFromSourceFile(QOpenGLShader.Vertex, str(SHADERS / "sky.vert"))
    prog.addShaderFromSourceFile(QOpenGLShader.Fragment, str(SHADERS / "sky.frag"))
    if not prog.link():
        return f"shader link failed: {prog.log()}"

    vao = QOpenGLVertexArrayObject()
    vao.create()

    fbo = QOpenGLFramebufferObject(QSize(width, height))
    fbo.bind()
    gl.glViewport(0, 0, width, height)
    prog.bind()
    vao.bind()

    # The same uniforms the app ships with, so this measures the real workload.
    p = ShardParams()
    prog.setUniformValue1f("uTanHalfFov", math.tan(math.radians(_FOV_DEGREES) / 2.0))
    prog.setUniformValue1f("uAspect", width / height)
    prog.setUniformValue1f("uNebula", float(p.nebula))
    prog.setUniformValue1f("uStarDensity", float(p.star_density))
    prog.setUniformValue1f("uStarBrightness", float(p.star_brightness))
    prog.setUniformValue("uNebulaColorA", QVector3D(*p.nebula_color_a))
    prog.setUniformValue("uNebulaColorB", QVector3D(*p.nebula_color_b))
    prog.setUniformValue("uCamRight", QVector3D(1.0, 0.0, 0.0))
    prog.setUniformValue("uCamUp", QVector3D(0.0, 1.0, 0.0))
    prog.setUniformValue("uCamForward", QVector3D(0.0, 0.0, -1.0))

    def draw(t):
        prog.setUniformValue1f("uTime", t)
        gl.glDrawArrays(GL_TRIANGLES, 0, 3)

    # Warm up: shader compile, first-use driver paths, clocks spinning up.
    for i in range(10):
        draw(i * 0.016)
    gl.glFinish()

    times = []
    for i in range(frames):
        start = time.perf_counter()
        draw(100.0 + i * 0.016)
        gl.glFinish()
        times.append((time.perf_counter() - start) * 1000.0)

    times.sort()
    median = times[len(times) // 2]
    renderer = gl.glGetString(GL_RENDERER)

    print(f"renderer : {renderer}")
    print(f"size     : {width}x{height} ({width * height / 1e6:.1f} Mpx)")
    print(f"frame    : {median:.2f} ms median  (min {times[0]:.2f}, max {times[-1]:.2f})")
    print(f"ceiling  : {1000.0 / median:.1f} FPS   [16 ms budget => "
          f"{'OK' if median <= 16.0 else 'MISSED'}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
