"""PySide6 GUI: a tabbed Stopwatch + Countdown Timer.

Thin view layer over the ``Stopwatch`` and ``Countdown`` models (both of which
are unit-tested headlessly). This file only renders state, forwards button
presses, and drives the audible/visual alert.

Run with:  python -m naive_timer
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QSurfaceFormat
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
from .shard import ShardParams, ShardWidget, default_surface_format
from .stopwatch import State, Stopwatch, format_elapsed
from . import sound, tuning

# ~60 FPS refresh for smooth animation.
FRAME_MS = 16

# QtMultimedia is optional; if unavailable we degrade to a visual-only alert.
try:
    from PySide6.QtMultimedia import QSoundEffect

    _HAVE_AUDIO = True
except Exception:  # pragma: no cover - depends on platform Qt build
    _HAVE_AUDIO = False


class StopwatchWidget(QWidget):
    def __init__(self, params: ShardParams | None = None) -> None:
        super().__init__()
        self._sw = Stopwatch()
        self._shard = ShardWidget(self._sw, params)

        self._start_btn = QPushButton("Start")
        self._start_btn.clicked.connect(self._on_toggle)
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._on_reset)

        buttons = QHBoxLayout()
        buttons.addWidget(self._start_btn)
        buttons.addWidget(reset_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._shard, stretch=1)
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
        self._shard.set_text(format_elapsed(self._sw.elapsed()))
        self._shard.advance(FRAME_MS / 1000.0)


class TimerWidget(QWidget):
    """Countdown that accepts a duration ('12m') or an alarm time ('02:54')."""

    def __init__(self, params: ShardParams | None = None) -> None:
        super().__init__()
        self._cd = Countdown()
        self._shard = ShardWidget(self._cd, params)
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
        layout.addWidget(self._shard, stretch=1)
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
        self._shard.set_alarm(False)
        if self._alert is not None:
            self._alert.stop()

    def _tick(self) -> None:
        self._shard.set_text(format_elapsed(self._cd.remaining()))
        self._shard.advance(FRAME_MS / 1000.0)

        # The alert is carried entirely by the shard: it fractures, then
        # breathes dark red. No background flash -- that read as jarring.
        if self._cd.alert_active():
            if not self._alerting:
                self._begin_alert()
        elif self._alerting:
            # Alert window elapsed on its own.
            self._stop_alert()
            self._start_btn.setText("Start")

    def _begin_alert(self) -> None:
        self._alerting = True
        self._status.setText("⏰ Time's up!")
        self._start_btn.setText("Start")
        self._dismiss_btn.setVisible(True)
        self._shard.set_alarm(True)
        if self._alert is not None:
            self._alert.play()


class _AlertPlayer:
    """The shatter, once, then the chime looping quietly until stopped.

    Both are synthesized at runtime (see ``sound.py``); no binary assets. Note
    that QSoundEffect decodes only uncompressed WAV -- it errors on FLAC.
    """

    def __init__(self) -> None:
        self._effect = QSoundEffect()
        self._effect.setSource(QUrl.fromLocalFile(sound.default_chime_path()))
        self._effect.setLoopCount(QSoundEffect.Loop.Infinite.value)
        self._effect.setVolume(0.35)

        # One-shot, played the instant the shard breaks. Its own file is
        # already ~7 dB below the reference recordings, so this stays near
        # unity; turn the WAV's `amplitude` down rather than this, so the
        # headroom is baked in.
        self._shatter = QSoundEffect()
        self._shatter.setSource(QUrl.fromLocalFile(sound.default_shatter_path()))
        self._shatter.setLoopCount(1)
        self._shatter.setVolume(0.9)

    def play(self) -> None:
        self._shatter.play()
        self._effect.play()

    def stop(self) -> None:
        self._shatter.stop()
        self._effect.stop()


class MainWindow(QTabWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Naive Linux Timer")
        # One ShardParams shared by both tabs, so the tuning panel moves both
        # shards at once. Tuning only the Timer tab looked like a dead slider
        # whenever the Stopwatch tab was in front.
        self.shard_params = ShardParams()
        self.stopwatch_tab = StopwatchWidget(self.shard_params)
        self.timer_tab = TimerWidget(self.shard_params)
        self.addTab(self.stopwatch_tab, "Stopwatch")
        self.addTab(self.timer_tab, "Timer")

    def shards(self) -> list[ShardWidget]:
        return [self.stopwatch_tab._shard, self.timer_tab._shard]


def main() -> int:
    # Must precede QApplication: the GL context is chosen at widget creation.
    QSurfaceFormat.setDefaultFormat(default_surface_format())

    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(420, 620)
    window.show()

    panel = None
    if tuning.enabled():
        panel = tuning.TuningPanel(window.shards())
        panel.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
