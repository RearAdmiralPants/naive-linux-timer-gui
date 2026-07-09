"""Headless smoke tests for the Qt layer.

Why this file exists: every model test passed while the app aborted on startup,
because ``_AlertPlayer`` passed a ``QSoundEffect`` enum where PySide6 6.11
wants an int. Compile-checking ``app.py`` could not catch that. Constructing
the objects can.

Two tiers, because Qt's ``offscreen`` platform has **no OpenGL at all** --
constructing a ``QOpenGLWidget`` under it segfaults, it does not raise:

* Always: things that need no GL context -- the alert player, the shard
  geometry, the text texture image.
* Only with a GL-capable platform: ``MainWindow``, which builds a
  ``ShardWidget``.

To get the GL tier headlessly (in CI, or a cloud container), run under a
virtual X server, which gives real GL via Mesa's software rasteriser:

    xvfb-run -a python -m unittest discover -s tests

Bare ``python -m unittest discover -s tests`` skips the GL tier and says so.
"""

import math
import os
import unittest

# Must be set before any QApplication is created. Respect an existing DISPLAY:
# if the developer has a screen, use it and get the GL tier for free.
if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - exercised only in Qt-less envs
    QApplication = None

_app = None


def setUpModule():
    global _app
    if QApplication is not None:
        from PySide6.QtGui import QSurfaceFormat

        from naive_timer.shard import default_surface_format

        QSurfaceFormat.setDefaultFormat(default_surface_format())
        _app = QApplication.instance() or QApplication([])


def _has_opengl() -> bool:
    """True when the running Qt platform can host a QOpenGLWidget.

    The ``offscreen`` plugin cannot, and finds out by crashing the process, so
    this must be checked *before* constructing one.
    """
    if QApplication is None:
        return False
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.platformName() != "offscreen"


needs_qt = unittest.skipIf(QApplication is None, "PySide6 not installed")


@needs_qt
class NoGlTest(unittest.TestCase):
    """Everything that must hold without a GL context."""

    def test_alert_player_loops_forever(self):
        from naive_timer import app

        if not app._HAVE_AUDIO:
            self.skipTest("QtMultimedia unavailable; alert is visual-only")

        from PySide6.QtMultimedia import QSoundEffect

        player = app._AlertPlayer()
        self.assertEqual(
            player._effect.loopCount(), QSoundEffect.Loop.Infinite.value
        )

    def test_geometry_is_whole_flat_shaded_facets(self):
        from naive_timer.shard import _OUTLINE, _build_geometry

        data = _build_geometry()
        floats_per_vertex = 11
        self.assertEqual(len(data) % floats_per_vertex, 0)

        vertices = len(data) // floats_per_vertex
        self.assertEqual(vertices, 3 * len(_OUTLINE), "one triangle per edge")

        for i in range(vertices):
            base = i * floats_per_vertex
            nx, ny, nz = data[base + 3 : base + 6]
            self.assertAlmostEqual(
                math.sqrt(nx * nx + ny * ny + nz * nz), 1.0, places=5,
                msg="facet normals must be unit length",
            )
            u, v = data[base + 6 : base + 8]
            self.assertTrue(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0)

    def test_text_image_has_ink_where_the_numerals_are(self):
        from naive_timer.shard import ShardParams, render_text_image

        blank = render_text_image("", ShardParams())
        drawn = render_text_image("00:12:34.56", ShardParams())

        self.assertEqual(blank.size(), drawn.size())

        def ink(image):
            return sum(
                image.pixelColor(x, y).alpha() > 0
                for y in range(0, image.height(), 8)
                for x in range(0, image.width(), 8)
            )

        self.assertEqual(ink(blank), 0, "empty text must draw nothing")
        self.assertGreater(ink(drawn), 0, "numerals must leave ink")


@needs_qt
class GlTest(unittest.TestCase):
    """Needs a real GL context. Run under xvfb-run when there's no display."""

    def setUp(self):
        # Must be checked here, not in a class decorator: decorators are
        # evaluated at import time, before setUpModule() has constructed the
        # QApplication, and platformName() is empty until then. Getting this
        # wrong lets the GL test run under `offscreen`, where constructing a
        # QOpenGLWidget segfaults rather than raising.
        if not _has_opengl():
            self.skipTest(
                "no OpenGL on this Qt platform; "
                "run under `xvfb-run -a` for the GL tier"
            )

    def test_main_window_constructs_and_shows(self):
        from naive_timer.app import MainWindow

        window = MainWindow()
        window.show()
        self.assertTrue(window.windowTitle())


if __name__ == "__main__":
    unittest.main()
