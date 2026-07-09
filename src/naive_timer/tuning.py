"""Live tuning panel for the shard shader. Development only.

Shown when the app is launched with ``NAIVE_TIMER_TUNE=1``. Drag the sliders,
watch the shard. When it looks right, hit **Print params** and paste the block
it writes to the console into ``ShardParams`` to make the look permanent.

Deliberately ugly and deliberately not in the shipped UI.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFontComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
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
    ("base_alpha", 0.0, 1.0),
]

_SKY_SLIDERS = [
    ("nebula", 0.0, 1.5),
    ("star_density", 4.0, 60.0),
    ("star_brightness", 0.0, 2.0),
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
        self.setMinimumWidth(320)

        outer = QVBoxLayout(self)
        self._labels: dict[str, QLabel] = {}

        outer.addWidget(self._slider_group("Glass", _SLIDERS))
        outer.addWidget(self._slider_group("Sky", _SKY_SLIDERS))

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

        outer.addWidget(appearance)

        dump = QPushButton("Print params")
        dump.clicked.connect(self._dump)
        outer.addWidget(dump)
        outer.addStretch(1)

    def _slider_group(self, title: str, specs) -> QGroupBox:
        box = QGroupBox(title)
        form = QFormLayout(box)
        for name, lo, hi in specs:
            slider = QSlider(Qt.Horizontal)
            slider.setRange(int(lo * 100), int(hi * 100))
            slider.setValue(int(getattr(self._params, name) * 100))
            label = QLabel(f"{getattr(self._params, name):.2f}")
            self._labels[name] = label
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

    def _dump(self) -> None:
        p: ShardParams = self._params
        print("\n# --- paste into ShardParams defaults ---")
        for name, _lo, _hi in _SLIDERS + _SKY_SLIDERS:
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
