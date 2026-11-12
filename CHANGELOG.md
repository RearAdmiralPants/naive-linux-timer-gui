# Changelog

Dates, not versions. Older history lives in `git log` and `docs/HANDOFF.md`.

- 2026-11-12 — Type Ia supernovae (M4): an eddy that accretes past `eddy_critical_mass` detonates, with a flash that lights all dust in range, a shock that pushes and heats the dust it crosses, and its captured clouds thrown clear to re-form downstream. Pull and glow grow as an eddy feeds.
- 2026-11-12 — Gravitational eddies (M2/M3): HDR cores with helical jets, dust captured onto tilted orbits (a churning torus), eddy-lit forward scattering, and release/re-clumping when an eddy loses its pull. "Eddies" section in the tuning panel.
- 2026-11-12 — Dust clouds (M1): GPU compute-simulated particle clouds with per-cloud albedo and Henyey–Greenstein anisotropy, premultiplied so low-albedo dust occludes. "Dust" section in the tuning panel. `render_still.py --sim`, `tools/bench_frame.py`.
- 2026-11-12 — `tools/usage_gate.py`: go/pause/stop gate for long agentic runs, based on five-hour pace and a weekly cap (via `claude-usage`).
- 2026-11-12 — Feature doc and decisions for dust clouds, gravitational eddies and albedo (`docs/features/gravitational-dust-eddies-albedo.md`).
