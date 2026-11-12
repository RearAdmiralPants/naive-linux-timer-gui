"""Eddy lifecycle and whole-cloud capture/release (eddies.py), headless."""

import math
import random
import unittest

from naive_timer.dust import spawn_cloud
from naive_timer.eddies import _RAMP_S, Eddy, EddySet, MAX_EDDIES
from naive_timer.shard import ShardParams


def _eddy(**kw):
    base = dict(pos=(0.0, 0.0, -2.0), axis=(0.0, 1.0, 0.0), color=(1, 1, 1),
                life=10.0, fade=4.0, spin=1.0)
    base.update(kw)
    return Eddy(**base)


class EnvelopeTest(unittest.TestCase):
    def test_ramps_holds_and_fades(self):
        e = _eddy()
        e.age = 0.0
        self.assertEqual(e.envelope(), 0.0)
        e.age = _RAMP_S / 2
        self.assertAlmostEqual(e.envelope(), 0.5)
        e.age = _RAMP_S + 5.0
        self.assertEqual(e.envelope(), 1.0)
        self.assertFalse(e.fading)
        e.age = _RAMP_S + 10.0 + 2.0      # halfway through the fade
        self.assertAlmostEqual(e.envelope(), 0.5)
        self.assertTrue(e.fading)
        e.age = _RAMP_S + 10.0 + 4.0
        self.assertEqual(e.envelope(), 0.0)
        self.assertFalse(e.dead)          # resting before rebirth
        e.age += 10.0
        self.assertTrue(e.dead)


class EddySetTest(unittest.TestCase):
    def setUp(self):
        self.p = ShardParams()

    def test_count_and_master_switch(self):
        es = EddySet(seed=1)
        es.sync_count(self.p)
        self.assertEqual(len(es.eddies), int(self.p.eddy_count))
        self.p.eddy_count = 99
        es.sync_count(self.p)
        self.assertEqual(len(es.eddies), MAX_EDDIES)
        self.p.eddies_enabled = False
        es.sync_count(self.p)
        self.assertEqual(es.eddies, [])

    def test_dead_eddy_is_reborn_elsewhere(self):
        es = EddySet(seed=2)
        self.p.eddy_count = 1
        es.sync_count(self.p)
        first = es.eddies[0]
        for _ in range(int((self.p.eddy_life_max + 40) / 0.1)):
            es.step(0.1, self.p, [])
            if es.eddies[0] is not first:
                break
        self.assertIsNot(es.eddies[0], first)
        self.assertEqual(es.eddies[0].age, 0.0)

    def test_axis_never_points_at_the_camera(self):
        rng_set = EddySet(seed=3)
        self.p.eddy_count = MAX_EDDIES
        for _ in range(20):
            rng_set.eddies.clear()
            rng_set.sync_count(self.p)
            for e in rng_set.eddies:
                self.assertLess(abs(e.axis[2]), 0.8)
                self.assertAlmostEqual(math.hypot(*e.axis), 1.0, places=6)

    def test_capture_parks_cloud_then_release_restores_drift(self):
        es = EddySet(seed=4)
        e = _eddy(life=5.0, fade=1.0)
        e.age = _RAMP_S  # at full pull
        es.eddies = [e]
        self.p.eddy_count = 1
        cloud = spawn_cloud(random.Random(1), self.p, anywhere=True)
        cloud.center = [0.5, 0.0, -2.0]   # well inside the capture radius
        base = cloud.base_vel
        for _ in range(int(4.0 / 0.05)):
            es._capture(0.05, self.p, [cloud])
            for k in range(3):
                cloud.center[k] += cloud.vel[k] * 0.05
        self.assertEqual(cloud.captured_by, id(e))
        self.assertLess(math.dist(cloud.center, e.pos), 0.5)
        self.assertGreater(e.mass_gained, 0.0)

        e.age = _RAMP_S + 5.0 + 1.0  # pull gone
        es._capture(0.05, self.p, [cloud])
        self.assertIsNone(cloud.captured_by)
        kick = self.p.eddy_release_kick
        for k in range(3):
            self.assertLessEqual(abs(cloud.vel[k] - base[k]), kick + 1e-9)

    def test_far_cloud_is_left_alone(self):
        es = EddySet(seed=5)
        e = _eddy()
        e.age = _RAMP_S
        es.eddies = [e]
        cloud = spawn_cloud(random.Random(2), self.p, anywhere=True)
        cloud.center = [6.0, 3.0, -8.0]
        before = list(cloud.vel)
        es._capture(0.05, self.p, [cloud])
        self.assertIsNone(cloud.captured_by)
        self.assertEqual(cloud.capture, 0.0)
        for a, b in zip(before, cloud.vel):
            self.assertAlmostEqual(a, b, places=3)


class SupernovaTest(unittest.TestCase):
    def setUp(self):
        self.p = ShardParams()
        self.es = EddySet(seed=6)
        self.e = _eddy(life=100.0)
        self.e.age = _RAMP_S
        self.es.eddies = [self.e]
        self.p.eddy_count = 1

    def test_feeding_grows_pull_and_glow(self):
        before = (self.e.pull(self.p), self.e.glow(self.p))
        self.e.mass_gained = self.p.eddy_critical_mass * 0.9
        self.assertGreater(self.e.pull(self.p), before[0])
        self.assertGreater(self.e.glow(self.p), before[1])

    def test_detonates_at_critical_mass_and_flings_its_clouds(self):
        cloud = spawn_cloud(random.Random(3), self.p, anywhere=True)
        cloud.center = [0.3, 0.0, -2.0]
        cloud.captured_by = id(self.e)
        self.e.mass_gained = self.p.eddy_critical_mass
        self.es.step(1 / 60, self.p, [cloud])
        self.assertIsNotNone(self.e.nova_age)
        self.assertEqual(self.e.envelope(), 0.0)
        self.assertIsNone(cloud.captured_by)
        # Thrown outward, i.e. along +x here, faster than its own drift.
        self.assertGreater(cloud.vel[0] - cloud.base_vel[0],
                           0.9 * self.p.nova_cloud_speed)
        # ... and keeps that throw instead of relaxing straight back.
        for _ in range(60):
            self.es.step(1 / 60, self.p, [cloud])
        self.assertGreater(cloud.vel[0] - cloud.base_vel[0],
                           0.9 * self.p.nova_cloud_speed)

    def test_blast_shape_and_rebirth(self):
        self.e.mass_gained = self.p.eddy_critical_mass
        self.es.step(1 / 60, self.p, [])
        e = self.e
        e.nova_age = 0.04
        rising = e.nova(self.p)[2]
        e.nova_age = 0.08
        peak = e.nova(self.p)[2]
        e.nova_age = 2.0
        late = e.nova(self.p)
        self.assertLess(rising, peak)
        self.assertAlmostEqual(peak, self.p.nova_flash)
        self.assertLess(late[2], peak * 0.1)
        self.assertGreater(late[0], 0.0)           # the shell has travelled
        e.nova_age = e.nova_duration + 0.1
        self.assertEqual(e.nova(self.p), (0.0, 0.0, 0.0, 0.0))
        e.nova_age = e.nova_duration + 10.0
        self.es.step(1 / 60, self.p, [])
        self.assertIsNot(self.es.eddies[0], e)     # reborn elsewhere

    def test_zero_critical_mass_never_detonates(self):
        self.p.eddy_critical_mass = 0.0
        self.e.mass_gained = 1e6
        self.es.step(1 / 60, self.p, [])
        self.assertIsNone(self.e.nova_age)


if __name__ == "__main__":
    unittest.main()
