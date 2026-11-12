"""Gravitational eddies: the CPU side (lifecycle, cloud capture), free of GL.

An eddy is born, holds its pull for a while, then "loses" it -- the strength
envelope fades -- and is reborn elsewhere. The GPU applies its gravity and
orbital guidance to every particle (dust_step.comp); this file decides where
eddies are, how strong they are right now, and what happens to whole clouds.

Cloud-level capture exists so that a captured cloud *stays*: its particles
orbit the eddy, so its home has to be there too, or they would be dragged
back across the frame toward a centre that has drifted on. A captured cloud
parks on the eddy; when the pull fades it is released with its old drift
restored plus a kick, and the cohesion spring pulls the scattered orbit back
into a cloud -- the "clump back together" phase.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

MAX_EDDIES = 8
_RAMP_S = 3.0      # how long a newborn eddy takes to reach full pull
_REST_S = 1.5      # gap between an eddy dying and its successor appearing

# Where eddies may appear. Inside the visible frustum for the default camera,
# and behind the shard's plane, so the camera is never inside a jet.
_SPAWN_X = 4.0
_SPAWN_Y = 2.2
_SPAWN_Z = (-6.0, -0.8)
_MIN_SEPARATION = 2.5


def _unit(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / n for c in v)


@dataclass
class Eddy:
    pos: tuple
    axis: tuple
    color: tuple
    life: float          # seconds of full pull, after the ramp
    fade: float          # seconds to lose it
    spin: float          # +1 / -1: which way the orbit turns about the axis
    age: float = 0.0
    mass_gained: float = 0.0   # dust accreted, in cloud-seconds (M4 uses it)

    def envelope(self) -> float:
        """0..1 strength: ramp up, hold, fade out ("losing pull")."""
        if self.age < _RAMP_S:
            return self.age / _RAMP_S
        over = self.age - _RAMP_S - self.life
        if over <= 0.0:
            return 1.0
        return max(0.0, 1.0 - over / max(self.fade, 1e-3))

    @property
    def fading(self) -> bool:
        return self.age > _RAMP_S + self.life

    @property
    def dead(self) -> bool:
        return self.age > _RAMP_S + self.life + self.fade + _REST_S


def spawn_eddy(rng: random.Random, params, others=()) -> Eddy:
    for _ in range(20):
        pos = (
            rng.uniform(-_SPAWN_X, _SPAWN_X),
            rng.uniform(-_SPAWN_Y, _SPAWN_Y),
            rng.uniform(*_SPAWN_Z),
        )
        if all(math.dist(pos, o.pos) >= _MIN_SEPARATION for o in others):
            break
    # Any orientation, but never pointing straight at the camera: a jet seen
    # end-on is a dot, which wastes the effect.
    while True:
        axis = _unit((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)))
        if abs(axis[2]) < 0.8:
            break
    mix = rng.random()
    color = tuple(a + (b - a) * mix
                  for a, b in zip(params.eddy_color_a, params.eddy_color_b))
    lo, hi = sorted((params.eddy_life_min, params.eddy_life_max))
    return Eddy(
        pos=pos, axis=axis, color=color,
        life=rng.uniform(lo, hi), fade=params.eddy_fade_s,
        spin=rng.choice((-1.0, 1.0)),
    )


class EddySet:
    def __init__(self, seed: int = 11) -> None:
        self._rng = random.Random(seed)
        self.eddies: list[Eddy] = []
        self._staggered = False

    def sync_count(self, params) -> None:
        want = 0
        if params.eddies_enabled:
            want = max(0, min(MAX_EDDIES, int(round(params.eddy_count))))
        while len(self.eddies) < want:
            e = spawn_eddy(self._rng, params, self.eddies)
            # Stagger the first generation so they do not all fade together.
            e.age = self._rng.uniform(0.0, _RAMP_S + e.life * 0.6)
            self.eddies.append(e)
        del self.eddies[want:]

    def step(self, dt: float, params, clouds) -> None:
        self.sync_count(params)
        for i, e in enumerate(self.eddies):
            e.age += dt
            if e.dead:
                self.eddies[i] = spawn_eddy(
                    self._rng, params, self.eddies[:i] + self.eddies[i + 1:]
                )
        self._capture(dt, params, clouds)

    def _capture(self, dt: float, params, clouds) -> None:
        """Pull whole clouds toward eddies; release them when the pull fades."""
        reach = params.eddy_capture_radius
        for c in clouds:
            best, best_w = None, 0.0
            for e in self.eddies:
                d = math.dist(c.center, e.pos)
                # Capture weight: full once the cloud's centre is inside the
                # capture radius (plus half the cloud -- its edge arrives
                # first), fading to zero at 1.3x that. Kept short on purpose:
                # at 2x it measured as one eddy swallowing 6 of 8 clouds in
                # 15 s, which is a supernova every few seconds, not a story.
                r = reach + 0.5 * c.radius
                w = max(0.0, min(1.0, (1.3 * r - d) / (0.3 * r))) * e.envelope()
                if w > best_w:
                    best, best_w = e, w
            if best is not None and best_w > 0.0:
                pull = params.eddy_cloud_pull * best_w
                for k in range(3):
                    # Critically-damped-ish spring toward the eddy: the cloud
                    # settles onto it instead of orbiting it as a rigid blob
                    # (the *particles* do the orbiting).
                    to = best.pos[k] - c.center[k]
                    v = c.vel[k] + (to * pull - c.vel[k] * 2.0 * math.sqrt(pull)) * dt
                    c.vel[k] = v
                best.mass_gained += best_w * c.fraction * dt
                c.captured_by = id(best)
                c.capture = best_w
            elif c.captured_by is not None:
                # Released: old drift back, plus a kick so it does not sit on
                # the corpse of the eddy waiting for the next one.
                kick = params.eddy_release_kick
                for k in range(3):
                    c.vel[k] = c.base_vel[k] + self._rng.uniform(-kick, kick)
                c.captured_by = None
                c.capture = 0.0
            else:
                # Free: relax back toward the drift it was born with (a
                # partial capture that never completed leaves a residue).
                for k in range(3):
                    c.vel[k] += (c.base_vel[k] - c.vel[k]) * min(1.0, 0.5 * dt)
