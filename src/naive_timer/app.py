"""PySide6 GUI: a tabbed Stopwatch + Countdown Timer.

Thin view layer over the ``Stopwatch`` and ``Countdown`` models (both of which
are unit-tested headlessly). This file only renders state, forwards button
presses, and drives the audible/visual alert.

Run with:  python -m naive_timer
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import Qt, QElapsedTimer, QTimer, QUrl
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


def _parse_cli(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Pure with respect to process state: tests pass an explicit ``argv`` (the
    args after the program name); ``None`` reads ``sys.argv``. argparse itself
    handles ``--help`` and usage errors, exiting 0 and 2 respectively.

    Returns a namespace with ``json`` (str | None), ``no_panel`` (bool), and
    ``timer`` (str | None).
    """
    parser = argparse.ArgumentParser(
        prog="naive-timer",
        description="A visually-appealing Linux stopwatch/timer.",
    )
    parser.add_argument(
        "--json",
        metavar="FILE",
        help="Load shard parameters from a JSON file and apply them on startup.",
    )
    parser.add_argument(
        "--no-panel",
        action="store_true",
        help="Never open the dev/tuning panel, even when NAIVE_TIMER_TUNE=1.",
    )
    parser.add_argument(
        "--timer",
        metavar="VALUE",
        help="Open on the Timer tab and start a countdown immediately. "
        "VALUE is parsed as a duration (e.g. '12m', '1h30m', '25:00') or, "
        "if that fails, as an alarm time (e.g. '02:54', '6:30pm'). "
        "On parse error the application exits with a non-zero status.",
    )
    return parser.parse_args(argv)


# Longest step we will hand the animation in one frame. A stall, a drag of the
# window, or a laptop resume can leave an arbitrarily large gap; without a clamp
# the camera would teleport rather than sway.
MAX_FRAME_S = 0.25


class FrameClock:
    """Real elapsed time between frames.

    The animation used to advance by a fixed FRAME_MS regardless of how long
    the frame actually took, so on a GPU that could not hold 60 FPS the sway,
    twinkle and drift all ran in slow motion -- at 27 ms/frame, 60% speed. The
    displayed time was always correct (that comes from the models, which read
    the wall clock); it was the animation that lagged. Measuring the interval
    makes animation speed the same on every machine.
    """

    def __init__(self) -> None:
        self._timer = QElapsedTimer()
        self._timer.start()

    def tick(self) -> float:
        """Seconds since the previous call, clamped."""
        return min(self._timer.restart() / 1000.0, MAX_FRAME_S)


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
        # True from the Reset shatter until the pieces clear and we zero out.
        self._resetting = False

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

        self._clock = FrameClock()
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(FRAME_MS)

    def _on_toggle(self) -> None:
        # Ignore Start/Pause while the shard is mid-shatter; the readout is
        # frozen and the model is being reset out from under it.
        if self._resetting:
            return
        self._sw.toggle()
        self._start_btn.setText(
            "Pause" if self._sw.state is State.RUNNING else "Start"
        )

    def _on_reset(self) -> None:
        # Reset shatters the shard rather than snapping to zero. Pausing first
        # freezes the readout at its final value so the numerals fly apart
        # showing that time; the model is zeroed only once the pieces clear
        # (see _tick), after which the shard reassembles at 00:00:00.
        if self._resetting:
            return
        self._resetting = True
        self._sw.pause()
        self._shard.set_alarm(True)
        self._start_btn.setText("Start")

    def _tick(self) -> None:
        if self._resetting and self._shard.pieces_have_cleared:
            self._sw.reset()
            self._shard.set_alarm(False)  # reassemble at zero
            self._resetting = False
        self._shard.set_text(format_elapsed(self._sw.elapsed()))
        self._shard.advance(self._clock.tick())


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

        self._clock = FrameClock()
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

    def start_with(self, seconds: float, display_text: str, mode: str) -> None:
        """Programmatically configure and start a countdown.

        Bypasses input parsing — ``seconds`` is already a validated, parsed
        value. ``display_text`` is shown in the text box so the user sees what
        was set. ``mode`` is one of "Duration" or "Alarm at" and controls
        the combo box selection.

        Called from ``main()`` when the ``--timer`` CLI flag is used.
        """
        self._input.setText(display_text)
        idx = self._mode.findText(mode)
        if idx >= 0:
            self._mode.setCurrentIndex(idx)
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
        self._shard.advance(self._clock.tick())

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
    def __init__(self, *, timer_value: tuple[float, str, str] | None = None) -> None:
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

        # --timer CLI flag: pre-configured countdown, jump to Timer tab.
        if timer_value is not None:
            seconds, display_text, mode = timer_value
            self.timer_tab.start_with(seconds, display_text, mode)
            self.setCurrentWidget(self.timer_tab)

    def shards(self) -> list[ShardWidget]:
        return [self.stopwatch_tab._shard, self.timer_tab._shard]


def main() -> int:
    # Parse CLI args before QApplication. argparse handles --help and usage
    # errors itself (exiting 0 / 2); we only handle our own concerns below.
    cli = _parse_cli()

    # Load JSON params if requested, before building any GL widgets.
    params_data: dict | None = None
    if cli.json is not None:
        try:
            params_data = tuning.load_params_file(cli.json)
        except tuning.ParamsError as exc:
            print(f"naive-timer: {exc}", file=sys.stderr)
            return 1
        print(f"[timer] loaded params from {cli.json}")

    # Parse --timer value before the GUI starts so errors exit cleanly.
    timer_value: tuple[float, str, str] | None = None
    if cli.timer is not None:
        raw = cli.timer.strip()
        try:
            seconds = parse_duration(raw)
            mode = "Duration"
        except ValueError:
            try:
                seconds = parse_alarm(raw)
                mode = "Alarm at"
            except ValueError as exc:
                print(f"naive-timer: cannot parse timer value {cli.timer!r}: {exc}", file=sys.stderr)
                return 1
        timer_value = (seconds, raw, mode)

    # Must precede QApplication: the GL context is chosen at widget creation.
    QSurfaceFormat.setDefaultFormat(default_surface_format())

    app = QApplication(sys.argv)
    window = MainWindow(timer_value=timer_value)

    # Apply CLI-loaded params to the shared ShardParams instance.
    if params_data is not None:
        tuning.apply_json_dict(window.shard_params, params_data)
        # Refresh both shards so the new params take effect immediately.
        for shard in window.shards():
            shard.refresh_params()

    window.resize(420, 620)
    window.show()

    # The dev/tuning panel is opt-in via NAIVE_TIMER_TUNE, and --no-panel
    # suppresses it -- e.g. to load a look cleanly without the debug window,
    # or to load one and keep tweaking it (env set, --no-panel absent).
    if tuning.enabled() and not cli.no_panel:
        panel = tuning.TuningPanel(window.shards())
        panel.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
