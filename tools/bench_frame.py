#!/usr/bin/env python3
"""Time whole frames of the real ShardWidget, with a feature on and off.

bench_sky.py times one pass; this times everything paintGL does (sky, dust,
shard, HDR chain), because a new pass is only expensive or cheap relative to
the frame it joins. The widget is never shown -- grabFramebuffer renders a
hidden QOpenGLWidget offscreen -- so it can run on a live desktop without a
window flashing up.

    PYTHONPATH=src .venv/bin/python tools/bench_frame.py --size 1920x1080 \
        --toggle dust_enabled
    # under a GPU choice:  source gpu-select.sh; gpu_select nvidia; ...

Prints ms/frame (median of --frames, after warm-up) for each side of
--toggle. Numbers include grabFramebuffer's readback, which is the same on
both sides, so read the *difference*.
"""

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtGui import QSurfaceFormat  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from naive_timer.shard import ShardParams, ShardWidget, default_surface_format  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--toggle", default="dust_enabled",
                    help="boolean ShardParams field to compare on vs off")
    ap.add_argument("--set", action="append", default=[],
                    help="name=value override, repeatable")
    args = ap.parse_args()

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QSurfaceFormat.setDefaultFormat(default_surface_format())
    app = QApplication(sys.argv[:1])

    params = ShardParams()
    for item in args.set:
        name, _, value = item.partition("=")
        setattr(params, name, float(value))
    w, h = (int(v) for v in args.size.split("x"))
    widget = ShardWidget(None, params)
    widget.resize(w, h)
    widget.set_text("12:34")
    widget.grabFramebuffer()  # initializeGL
    ctx = widget.context()
    print(f"renderer: {ctx.functions().glGetString(0x1F01)}  {w}x{h}")
    # A disabled feature benchmarks as free. That once went unnoticed for a
    # whole milestone on NVIDIA (bare 3.3 context, dust off), so refuse.
    if args.toggle in ("dust_enabled", "eddies_enabled") and not widget._dust.available:
        print(f"error: dust is unavailable here ({widget._dust.error}); "
              "on/off timings would be meaningless", file=sys.stderr)
        return 1

    for state in (False, True):
        setattr(params, args.toggle, state)
        times = []
        for i in range(args.frames + 10):
            widget.advance(1 / 60)
            t0 = time.perf_counter()
            widget.grabFramebuffer()
            app.processEvents()
            if i >= 10:
                times.append((time.perf_counter() - t0) * 1000)
        med = statistics.median(times)
        print(f"  {args.toggle}={state!s:5}  {med:6.2f} ms/frame  "
              f"(~{1000 / med:.0f} fps incl. readback)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
