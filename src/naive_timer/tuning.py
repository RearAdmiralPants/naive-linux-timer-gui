"""Live tuning panel for the shard shader. Development only.

Shown when the app is launched with ``NAIVE_TIMER_TUNE=1``. Drag the sliders,
watch the shard. When it looks right, hit **Print params** and paste the block
it writes to the console into ``ShardParams`` to make the look permanent.

Deliberately ugly and deliberately not in the shipped UI.
"""

from __future__ import annotations

import dataclasses
import json
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .shard import (
    ShardParams,
    ShardWidget,
    format_hex_color,
    parse_hex_color,
)


def enabled() -> bool:
    return os.environ.get("NAIVE_TIMER_TUNE") == "1"


def params_to_json(params: ShardParams) -> str:
    """A ShardParams as pretty JSON. Colour tuples become JSON arrays."""
    return json.dumps(dataclasses.asdict(params), indent=2)


def apply_json_dict(params: ShardParams, data: dict) -> None:
    """Fold a loaded dict into ``params`` in place.

    Only known fields are touched, so a file from an older or newer build loads
    what it can and ignores the rest instead of crashing. JSON has no tuples, so
    any field whose current value is a tuple (the colours) is coerced back --
    the shader indexes colours as ``rgb[0..2]`` and a stray list would still
    work, but keeping the type honest avoids surprises elsewhere.
    """
    for name, value in data.items():
        if not hasattr(params, name):
            continue
        if isinstance(getattr(params, name), tuple):
            value = tuple(value)
        setattr(params, name, value)


# name, minimum, maximum  (floats, scaled by 100 through the int slider)
_SLIDERS = [
    ("light_x", -5.0, 5.0),
    ("light_y", -5.0, 5.0),
    ("light_z", 0.5, 6.0),
    ("spec_power", 1.0, 160.0),
    ("spec_strength", 0.0, 2.0),
    ("fresnel", 0.0, 2.0),
    ("glow", 0.0, 2.0),
    ("etch", 0.0, 1.0),
    ("etch_depth", 0.0, 12.0),
    ("base_alpha", 0.0, 1.0),
]

_SKY_SLIDERS = [
    ("nebula", 0.0, 1.5),
    ("star_density", 10.0, 200.0),
    ("star_brightness", 0.0, 2.0),
]

_CAMERA_SLIDERS = [
    ("orbit_speed", 0.0, 0.8),
    ("sway_degrees", 0.0, 180.0),   # 180 = a full orbit; the numerals turn away
    ("orbit_radius", 2.0, 6.0),
    ("orbit_height", -1.5, 2.0),
    ("orbit_bob", 0.0, 1.0),
    ("idle_spin", 0.0, 0.6),
]

class _HexColorEdit(QLineEdit):
    """A 24-bit RRGGBB entry that only applies a value once it is valid.

    Typing "#ff" should not blank the shard on the way to "#ff8800", so an
    unparseable value tints the field red and changes nothing.
    """

    def __init__(self, initial: tuple, on_change) -> None:
        super().__init__(format_hex_color(initial))
        self._on_change = on_change
        self.setMaxLength(7)
        self.setPlaceholderText("#rrggbb")
        self.textChanged.connect(self._apply)

    def _apply(self, text: str) -> None:
        try:
            rgb = parse_hex_color(text)
        except ValueError:
            self.setStyleSheet("background-color:#5a2020;")
            return
        self.setStyleSheet("")
        self._on_change(rgb)


class TuningPanel(QWidget):
    """Drives every shard at once; they share one ShardParams."""

    def __init__(self, shards: list[ShardWidget]) -> None:
        super().__init__()
        if isinstance(shards, ShardWidget):  # tolerate a single shard
            shards = [shards]
        self._shards = shards
        self._params = shards[0].params
        # A Tool window floats above the app and takes no taskbar slot, so it
        # can't be mistaken for a second main window.
        self.setWindowFlag(Qt.Tool, True)
        self.setWindowTitle("Shard tuning (dev)")
        self.setMinimumWidth(640)

        outer = QVBoxLayout(self)
        self._labels: dict[str, QLabel] = {}
        self._sliders: dict[str, QSlider] = {}

        # Two columns so the panel stops overflowing the screen. The split is
        # semantic, not just arithmetic: the left column is how the shard
        # *looks* (its glass and the colour/font appearance box), the right is
        # the *scene* it sits in (camera and sky). That also balances the
        # heights — the tall Glass group is offset by the two shorter scene
        # groups stacked together.
        columns = QHBoxLayout()
        outer.addLayout(columns)
        left = QVBoxLayout()
        right = QVBoxLayout()
        columns.addLayout(left)
        columns.addLayout(right)

        left.addWidget(self._slider_group("Glass", _SLIDERS))
        right.addWidget(self._slider_group("Camera", _CAMERA_SLIDERS))
        right.addWidget(self._slider_group("Sky", _SKY_SLIDERS))

        appearance = QGroupBox("Numerals")
        aform = QFormLayout(appearance)

        self._font_combo = QFontComboBox()
        self._font_combo.setCurrentFont(QFont(self._params.font_family))
        self._font_combo.currentFontChanged.connect(self._on_font)
        aform.addRow("font", self._font_combo)

        self._bold = QCheckBox()
        self._bold.setChecked(self._params.font_bold)
        self._bold.toggled.connect(self._on_bold)
        aform.addRow("bold", self._bold)

        self._text_color = _HexColorEdit(
            self._params.text_color, lambda c: self._set("text_color", c)
        )
        aform.addRow("text / glow", self._text_color)

        self._glass_color = _HexColorEdit(
            self._params.glass_color, lambda c: self._set("glass_color", c)
        )
        aform.addRow("glass", self._glass_color)

        self._light_color = _HexColorEdit(
            self._params.light_color, lambda c: self._set("light_color", c)
        )
        aform.addRow("light", self._light_color)

        self._nebula_a = _HexColorEdit(
            self._params.nebula_color_a,
            lambda c: self._set("nebula_color_a", c),
        )
        aform.addRow("nebula A", self._nebula_a)

        self._nebula_b = _HexColorEdit(
            self._params.nebula_color_b,
            lambda c: self._set("nebula_color_b", c),
        )
        aform.addRow("nebula B", self._nebula_b)

        left.addWidget(appearance)

        # Pin each column's groups to the top; the shorter one pads at the
        # bottom rather than stretching its groups to fill.
        left.addStretch(1)
        right.addStretch(1)

        # Where Save/Load default to, remembered across a session so the second
        # click doesn't make you navigate again.
        self._settings_path = os.path.join(os.getcwd(), "shard_params.json")

        buttons = QHBoxLayout()
        for text, slot in (
            ("Save…", self._save),
            ("Load…", self._load),
            ("Print params", self._dump),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        outer.addLayout(buttons)

        # Every control now exists, so a startup file can drive them all.
        self._autoload()

    def _slider_group(self, title: str, specs) -> QGroupBox:
        box = QGroupBox(title)
        form = QFormLayout(box)
        for name, lo, hi in specs:
            slider = QSlider(Qt.Horizontal)
            slider.setRange(int(lo * 100), int(hi * 100))
            slider.setValue(int(getattr(self._params, name) * 100))
            label = QLabel(f"{getattr(self._params, name):.2f}")
            self._labels[name] = label
            self._sliders[name] = slider
            slider.valueChanged.connect(
                lambda v, n=name: self._on_slider(n, v / 100.0)
            )
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(slider)
            row_layout.addWidget(label)
            form.addRow(name, row)
        return box

    def _on_slider(self, name: str, value: float) -> None:
        self._labels[name].setText(f"{value:.2f}")
        self._set(name, value)

    def _on_font(self, font) -> None:
        self._set("font_family", font.family())

    def _on_bold(self, checked: bool) -> None:
        self._set("font_bold", checked)

    def _set(self, name: str, value) -> None:
        setattr(self._params, name, value)
        # Refresh every shard, not just the visible one: a slider that only
        # moved the Timer tab looked dead while the Stopwatch tab was in front.
        for shard in self._shards:
            shard.refresh_params()

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save shard settings", self._settings_path,
            "JSON (*.json)",
        )
        if not path:
            return
        self._settings_path = path
        try:
            with open(path, "w") as fh:
                fh.write(params_to_json(self._params))
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load shard settings", self._settings_path,
            "JSON (*.json)",
        )
        if not path:
            return
        self._settings_path = path
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Load failed", str(exc))
            return

        self._apply_loaded(data)

    def _apply_loaded(self, data: dict) -> None:
        """Fold a loaded dict into the params, then make it visible.

        Shared by the Load button and startup auto-load: update params, pull the
        widgets back into line, and repaint every shard.
        """
        apply_json_dict(self._params, data)
        self._sync_widgets()
        for shard in self._shards:
            shard.refresh_params()

    # The file auto-loaded from the working directory at startup, if present.
    # Kept distinct from the Save/Load default (shard_params.json) so an
    # experimental save doesn't silently become the next launch's defaults --
    # you promote a look to the default by copying it to this name on purpose.
    AUTOLOAD_NAME = "default-params.json"

    def _autoload(self) -> None:
        path = os.path.join(os.getcwd(), self.AUTOLOAD_NAME)
        if not os.path.exists(path):
            return
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            # A broken dev file must not stop the app from starting; a console
            # note is enough, and a modal on launch would just be in the way.
            print(f"[tuning] ignoring {path}: {exc}")
            return
        self._apply_loaded(data)
        print(f"[tuning] loaded startup params from {path}")

    def _sync_widgets(self) -> None:
        """Pull every control back into line with ``self._params``.

        Load is the only path that changes params behind the widgets' backs, so
        signals are blocked here: we set each control's displayed value without
        letting it echo back into params (and without firing a shard refresh per
        control -- the caller refreshes once at the end).
        """
        for name, slider in self._sliders.items():
            value = getattr(self._params, name)
            slider.blockSignals(True)
            slider.setValue(int(value * 100))
            slider.blockSignals(False)
            self._labels[name].setText(f"{value:.2f}")

        self._font_combo.blockSignals(True)
        self._font_combo.setCurrentFont(QFont(self._params.font_family))
        self._font_combo.blockSignals(False)

        self._bold.blockSignals(True)
        self._bold.setChecked(self._params.font_bold)
        self._bold.blockSignals(False)

        for edit, name in (
            (self._text_color, "text_color"),
            (self._glass_color, "glass_color"),
            (self._light_color, "light_color"),
            (self._nebula_a, "nebula_color_a"),
            (self._nebula_b, "nebula_color_b"),
        ):
            edit.blockSignals(True)
            edit.setText(format_hex_color(getattr(self._params, name)))
            edit.setStyleSheet("")
            edit.blockSignals(False)

    def _dump(self) -> None:
        p: ShardParams = self._params
        print("\n# --- paste into ShardParams defaults ---")
        for name, _lo, _hi in _SLIDERS + _CAMERA_SLIDERS + _SKY_SLIDERS:
            print(f"    {name}: float = {getattr(p, name):.2f}")
        for name in (
            "glass_color", "text_color", "light_color",
            "nebula_color_a", "nebula_color_b",
        ):
            rgb = getattr(p, name)
            pretty = ", ".join(f"{c:.3f}" for c in rgb)
            print(f"    {name}: tuple = ({pretty})  # {format_hex_color(rgb)}")
        print(f'    font_family: str = "{p.font_family}"')
        print(f"    font_bold: bool = {p.font_bold}")
        print("# ---------------------------------------\n")
