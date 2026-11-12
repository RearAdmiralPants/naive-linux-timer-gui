#!/usr/bin/env python3
"""Render one still on whatever GPU the environment selects, without a window.

render_still.py shows its widget, so on a live desktop it flashes a window;
under xvfb-run it only ever exercises llvmpipe. This renders hidden on the
real driver -- the case that caught NVIDIA returning a bare 3.3 context.

    (source gpu-select.sh; gpu_select nvidia; \
     .venv/bin/python tools/snap_gpu.py out.png --sim 20)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtGui import QSurfaceFormat  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from naive_timer.shard import ShardParams, ShardWidget, default_surface_format  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--sim", type=float, default=15.0)
    ap.add_argument("--size", default="640x480")
    args = ap.parse_args()

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QSurfaceFormat.setDefaultFormat(default_surface_format())
    app = QApplication(sys.argv[:1])  # noqa: F841 -- must outlive the widget
    w, h = (int(v) for v in args.size.split("x"))
    widget = ShardWidget(None, ShardParams())
    widget.resize(w, h)
    widget.set_text("12:34")
    widget.grabFramebuffer()  # initializeGL
    fmt = widget.context().format()
    print(f"renderer: {widget.context().functions().glGetString(0x1F01)} "
          f"GL {fmt.majorVersion()}.{fmt.minorVersion()} "
          f"dust available: {widget._dust.available}")
    widget._dust.simulate(args.sim)
    widget._elapsed = args.sim
    widget.grabFramebuffer().save(args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
