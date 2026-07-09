"""Headless smoke test: the Qt layer must at least construct.

The models are covered exhaustively elsewhere. This file exists for a narrower
reason: every model test passed while the app aborted on startup, because
``_AlertPlayer`` passed a ``QSoundEffect`` enum where PySide6 6.11 wants an
int. Compile-checking ``app.py`` cannot catch that; constructing the widgets
can. The ``offscreen`` platform makes it work with no display, so this runs in
CI and in a cloud container.

Keep these tests shallow. Anything that can be asserted without Qt belongs in
the model tests instead.
"""

import os
import unittest

# Must be set before any QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - exercised only in Qt-less envs
    QApplication = None

_app = None


def setUpModule():
    global _app
    if QApplication is not None:
        _app = QApplication.instance() or QApplication([])


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class GuiSmokeTest(unittest.TestCase):
    def test_main_window_constructs_and_shows(self):
        from naive_timer.app import MainWindow

        window = MainWindow()
        window.show()
        self.assertTrue(window.windowTitle())

    def test_alert_player_loops_forever(self):
        from naive_timer import app

        if not app._HAVE_AUDIO:
            self.skipTest("QtMultimedia unavailable; alert is visual-only")

        from PySide6.QtMultimedia import QSoundEffect

        player = app._AlertPlayer()
        self.assertEqual(
            player._effect.loopCount(), QSoundEffect.Loop.Infinite.value
        )


if __name__ == "__main__":
    unittest.main()
