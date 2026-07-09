"""PySide6 GUI: a tabbed Stopwatch + Countdown Timer.

Thin view layer over the ``Stopwatch`` and ``Countdown`` models (both of which
are unit-tested headlessly). This file only renders state, forwards button
presses, and drives the audible/visual alert.

Run with:  python -m naive_timer
"""

from __future__ import annotations

import math
import sys

from PySide6.QtCore import Qt, QTimer, QPointF, QUrl
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .countdown import Countdown, parse_alarm, parse_duration
from .stopwatch import State, Stopwatch, format_elapsed
from . import sound

# ~60 FPS refresh for smooth animation.
FRAME_MS = 16

# QtMultimedia is optional; if unavailable we degrade to a visual-only alert.
try:
    from PySide6.QtMultimedia import QSoundEffect

    _HAVE_AUDIO = True
except Exception:  # pragma: no cover - depends on platform Qt build
    _HAVE_AUDIO = False


class SpinnerWidget(QWidget):
    """A naive pseudo-3D ring that spins faster while its model is running.

    ``model`` only needs an ``is_running`` boolean.
    """

    def __init__(self, model) -> None:
        super().__init__()
        self._model = model
        self._angle = 0.0
        self._alarm = False
        self.setMinimumSize(240, 240)

    def set_alarm(self, active: bool) -> None:
        self._alarm = active

    def advance(self, dt: float) -> None:
        if self._alarm:
            speed = 360.0
        elif self._model.is_running:
            speed = 220.0
        else:
            speed = 30.0
        self._angle = (self._angle + speed * dt) % 360.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        cx, cy = rect.width() / 2.0, rect.height() / 2.0
        radius = min(cx, cy) - 20.0

        pulse = 1.0 + 0.06 * math.sin(math.radians(self._angle * 3))
        r = radius * pulse

        grad = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
        if self._alarm:
            grad.setColorAt(0.0, QColor(255, 70, 70))
            grad.setColorAt(1.0, QColor(255, 180, 40))
        else:
            base = 200 if self._model.is_running else 120
            grad.setColorAt(0.0, QColor(80, base, 255))
            grad.setColorAt(1.0, QColor(255, 80, base))
        pen = QPen(grad, 10)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        p.setPen(Qt.NoPen)
        for i in range(6):
            a = math.radians(self._angle + i * 60.0)
            depth = 0.6 + 0.4 * math.cos(a)
            dx = cx + r * math.cos(a)
            dy = cy + r * math.sin(a)
            dot = 6.0 + 6.0 * depth
            color = QColor(255, 255, 255, int(120 + 135 * depth))
            p.setBrush(color)
            p.drawEllipse(QPointF(dx, dy), dot, dot)
        p.end()


def _display_font() -> QFont:
    font = QFont("monospace")
    font.setPointSize(36)
    font.setBold(True)
    return font


class StopwatchWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._sw = Stopwatch()
        self._spinner = SpinnerWidget(self._sw)

        self._display = QLabel(format_elapsed(0))
        self._display.setAlignment(Qt.AlignCenter)
        self._display.setFont(_display_font())

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

        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(FRAME_MS)

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


class TimerWidget(QWidget):
    """Countdown that accepts a duration ('12m') or an alarm time ('02:54')."""

    def __init__(self) -> None:
        super().__init__()
        self._cd = Countdown()
        self._spinner = SpinnerWidget(self._cd)
        self._alerting = False
        self._alert = _AlertPlayer() if _HAVE_AUDIO else None

        self._mode = QComboBox()
        self._mode.addItems(["Duration", "Alarm at"])
        self._input = QLineEdit()
        self._input.setPlaceholderText("e.g. 12m  ·  1h30m  ·  25:00")
        self._input.returnPressed.connect(self._on_start)
        self._mode.currentIndexChanged.connect(self._update_placeholder)

        input_row = QHBoxLayout()
        input_row.addWidget(self._mode)
        input_row.addWidget(self._input, stretch=1)

        self._display = QLabel(format_elapsed(0))
        self._display.setAlignment(Qt.AlignCenter)
        self._display.setFont(_display_font())

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)

        self._start_btn = QPushButton("Start")
        self._start_btn.clicked.connect(self._on_start)
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._on_reset)
        self._dismiss_btn = QPushButton("Dismiss")
        self._dismiss_btn.clicked.connect(self._on_dismiss)
        self._dismiss_btn.setVisible(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self._start_btn)
        buttons.addWidget(reset_btn)
        buttons.addWidget(self._dismiss_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(input_row)
        layout.addWidget(self._spinner, stretch=1)
        layout.addWidget(self._display)
        layout.addWidget(self._status)
        layout.addLayout(buttons)

        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(FRAME_MS)

    def _update_placeholder(self) -> None:
        if self._mode.currentText() == "Duration":
            self._input.setPlaceholderText("e.g. 12m  ·  1h30m  ·  25:00")
        else:
            self._input.setPlaceholderText("e.g. 02:54  ·  6:30pm  ·  14:00")

    def _on_start(self) -> None:
        # If paused mid-countdown, Start just resumes.
        from .countdown import Phase

        if self._cd.phase is Phase.PAUSED:
            self._cd.start()
            self._start_btn.setText("Pause")
            return
        if self._cd.is_running:
            self._cd.pause()
            self._start_btn.setText("Start")
            return

        text = self._input.text().strip()
        try:
            if self._mode.currentText() == "Duration":
                seconds = parse_duration(text)
            else:
                seconds = parse_alarm(text)
        except ValueError as exc:
            self._status.setText(f"⚠ {exc}")
            return

        self._cd.configure(seconds)
        self._cd.start()
        self._status.setText("")
        self._start_btn.setText("Pause")

    def _on_reset(self) -> None:
        self._stop_alert()
        self._cd.reset()
        self._start_btn.setText("Start")
        self._status.setText("")

    def _on_dismiss(self) -> None:
        self._stop_alert()
        self._cd.dismiss()

    def _stop_alert(self) -> None:
        self._alerting = False
        self._dismiss_btn.setVisible(False)
        self._spinner.set_alarm(False)
        self.setStyleSheet("")
        if self._alert is not None:
            self._alert.stop()

    def _tick(self) -> None:
        self._spinner.advance(FRAME_MS / 1000.0)
        self._display.setText(format_elapsed(self._cd.remaining()))

        if self._cd.alert_active():
            if not self._alerting:
                self._begin_alert()
            # Flash the background for a visible pulse.
            flash = (self._spinner._angle % 60) < 30
            self.setStyleSheet(
                "background-color:#5a1414;" if flash else "background-color:#2a0a0a;"
            )
        elif self._alerting:
            # Alert window elapsed on its own.
            self._stop_alert()
            self._start_btn.setText("Start")

    def _begin_alert(self) -> None:
        self._alerting = True
        self._status.setText("⏰ Time's up!")
        self._start_btn.setText("Start")
        self._dismiss_btn.setVisible(True)
        self._spinner.set_alarm(True)
        if self._alert is not None:
            self._alert.play()


class _AlertPlayer:
    """Loops the generated chime quietly until stopped."""

    def __init__(self) -> None:
        self._effect = QSoundEffect()
        self._effect.setSource(QUrl.fromLocalFile(sound.default_chime_path()))
        self._effect.setLoopCount(QSoundEffect.Infinite)
        self._effect.setVolume(0.35)

    def play(self) -> None:
        self._effect.play()

    def stop(self) -> None:
        self._effect.stop()


class MainWindow(QTabWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Naive Linux Timer")
        self.addTab(StopwatchWidget(), "Stopwatch")
        self.addTab(TimerWidget(), "Timer")


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(360, 560)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
