"""PySide6 GUI for the naive stopwatch.

This is a thin view layer over ``Stopwatch``. All timekeeping lives in the
model (which is unit-tested headlessly); this file only renders state and
forwards button presses.

The "naive 3D/animation" is a spinning, pulsing ring drawn with QPainter whose
rotation speed tracks whether the stopwatch is running. It's intentionally
simple — a starting point to build fancier effects on.

Run with:  python -m naive_timer
"""

from __future__ import annotations

import math
import sys

from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .stopwatch import State, Stopwatch, format_elapsed

# ~60 FPS refresh for smooth animation.
FRAME_MS = 16


class SpinnerWidget(QWidget):
    """A naive pseudo-3D ring that spins faster while the watch runs."""

    def __init__(self, stopwatch: Stopwatch) -> None:
        super().__init__()
        self._sw = stopwatch
        self._angle = 0.0
        self.setMinimumSize(240, 240)

    def advance(self, dt: float) -> None:
        speed = 220.0 if self._sw.is_running else 30.0  # degrees/sec
        self._angle = (self._angle + speed * dt) % 360.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        cx, cy = rect.width() / 2.0, rect.height() / 2.0
        radius = min(cx, cy) - 20.0

        # Pulsing scale gives a naive sense of depth.
        pulse = 1.0 + 0.06 * math.sin(math.radians(self._angle * 3))
        r = radius * pulse

        # Rotating gradient ring.
        grad = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
        base = 200 if self._sw.is_running else 120
        grad.setColorAt(0.0, QColor(80, base, 255))
        grad.setColorAt(1.0, QColor(255, 80, base))
        pen = QPen(grad, 10)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # A few orbiting dots for the "3D-ish" motion.
        p.setPen(Qt.NoPen)
        for i in range(6):
            a = math.radians(self._angle + i * 60.0)
            depth = 0.6 + 0.4 * math.cos(a)  # fake depth via size/alpha
            dx = cx + r * math.cos(a)
            dy = cy + r * math.sin(a)
            dot = 6.0 + 6.0 * depth
            color = QColor(255, 255, 255, int(120 + 135 * depth))
            p.setBrush(color)
            p.drawEllipse(QPointF(dx, dy), dot, dot)
        p.end()


class TimerWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Naive Linux Timer")
        self._sw = Stopwatch()

        self._spinner = SpinnerWidget(self._sw)

        self._display = QLabel(format_elapsed(0))
        self._display.setAlignment(Qt.AlignCenter)
        font = QFont("monospace")
        font.setPointSize(36)
        font.setBold(True)
        self._display.setFont(font)

        self._start_btn = QPushButton("Start")
        self._start_btn.clicked.connect(self._on_toggle)
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._on_reset)

        buttons = QHBoxLayout()
        buttons.addWidget(self._start_btn)
        buttons.addWidget(reset_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._spinner, stretch=1)
        layout.addWidget(self._display)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(FRAME_MS)

    def _on_toggle(self) -> None:
        self._sw.toggle()
        self._start_btn.setText(
            "Pause" if self._sw.state is State.RUNNING else "Start"
        )

    def _on_reset(self) -> None:
        self._sw.reset()
        self._start_btn.setText("Start")

    def _tick(self) -> None:
        self._spinner.advance(FRAME_MS / 1000.0)
        self._display.setText(format_elapsed(self._sw.elapsed()))


def main() -> int:
    app = QApplication(sys.argv)
    window = TimerWindow()
    window.resize(360, 500)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
