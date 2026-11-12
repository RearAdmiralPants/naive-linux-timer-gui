"""The CPU half of the dust field: spawn ranges, drift, respawn, packing.

The GPU half (dust_step.comp / dust.vert) is exercised by test_gui_smoke's GL
tier and, for how it actually looks, by tools/render_still.py --sim.
"""

import struct
import unittest

from naive_timer.dust import (
    BOUNDS_X,
    MAX_CLOUDS,
    _CLOUD_FLOATS,
    CloudSet,
    out_of_bounds,
)
from naive_timer.shard import ShardParams


class CloudSetTest(unittest.TestCase):
    def setUp(self):
        self.params = ShardParams()

    def test_count_follows_params_and_is_capped(self):
        cs = CloudSet(seed=3)
        cs.sync_count(self.params)
        self.assertEqual(len(cs.clouds), int(self.params.dust_clouds))
        self.params.dust_clouds = 999
        cs.sync_count(self.params)
        self.assertEqual(len(cs.clouds), MAX_CLOUDS)
        self.params.dust_clouds = 0
        cs.sync_count(self.params)
        self.assertEqual(cs.clouds, [])

    def test_per_cloud_values_stay_inside_their_ranges(self):
        p = self.params
        cs = CloudSet(seed=5)
        p.dust_clouds = MAX_CLOUDS
        cs.sync_count(p)
        for c in cs.clouds:
            self.assertTrue(p.dust_albedo_min <= c.albedo <= p.dust_albedo_max)
            self.assertTrue(p.dust_aniso_min <= c.aniso <= p.dust_aniso_max)
            self.assertTrue(p.dust_size_min <= c.radius <= p.dust_size_max)
            self.assertTrue(p.dust_volume_min <= c.fraction <= p.dust_volume_max)
            speed = abs(c.vel[0])
            self.assertTrue(p.dust_speed_min <= speed <= p.dust_speed_max)

    def test_inverted_range_is_tolerated(self):
        # Sliders are independent, so min can be dragged above max.
        self.params.dust_albedo_min, self.params.dust_albedo_max = 0.9, 0.2
        cs = CloudSet(seed=1)
        cs.sync_count(self.params)
        for c in cs.clouds:
            self.assertTrue(0.2 <= c.albedo <= 0.9)

    def test_clouds_drift_out_and_respawn_upwind_with_new_generation(self):
        cs = CloudSet(seed=7)
        self.params.dust_clouds = 1
        self.params.dust_speed_min = self.params.dust_speed_max = 1.0
        cs.sync_count(self.params)
        first = cs.clouds[0]
        gen = first.generation
        heading = 1.0 if first.vel[0] > 0 else -1.0
        for _ in range(2000):  # 2000 * 0.05 s at 1 unit/s crosses the volume
            cs.step(0.05, self.params)
            if cs.clouds[0].generation != gen:
                break
        new = cs.clouds[0]
        self.assertGreater(new.generation, gen)
        self.assertFalse(out_of_bounds(new))
        # Enters at the edge it will drift away from, i.e. off-frame.
        self.assertGreaterEqual(abs(new.center[0]), BOUNDS_X)
        new_heading = 1.0 if new.vel[0] > 0 else -1.0
        self.assertEqual(new.center[0] * new_heading < 0, True)
        del heading

    def test_generations_are_never_reused_across_slots(self):
        # A slot re-filled after a count change must not inherit a generation
        # its stale particles already match, or they would never re-seed.
        cs = CloudSet(seed=2)
        cs.sync_count(self.params)
        seen = {c.generation for c in cs.clouds}
        self.params.dust_clouds = 2
        cs.sync_count(self.params)
        self.params.dust_clouds = 8
        cs.sync_count(self.params)
        refilled = {c.generation for c in cs.clouds[2:]}
        self.assertFalse(refilled & seen)

    def test_pack_layout(self):
        cs = CloudSet(seed=4)
        cs.sync_count(self.params)
        data = cs.pack()
        self.assertEqual(len(data), len(cs.clouds) * _CLOUD_FLOATS * 4)
        floats = struct.unpack(f"{len(data) // 4}f", data)
        c = cs.clouds[0]
        self.assertAlmostEqual(floats[3], c.radius, places=5)
        self.assertEqual(floats[7], float(c.generation))
        self.assertAlmostEqual(floats[11], c.albedo, places=5)

    def test_pack_never_empty(self):
        cs = CloudSet(seed=4)
        self.params.dust_clouds = 0
        cs.sync_count(self.params)
        self.assertEqual(len(cs.pack()), _CLOUD_FLOATS * 4)

    def test_same_seed_same_field(self):
        a, b = CloudSet(seed=9), CloudSet(seed=9)
        for cs in (a, b):
            cs.sync_count(self.params)
            for _ in range(50):
                cs.step(0.1, self.params)
        self.assertEqual(a.pack(), b.pack())


if __name__ == "__main__":
    unittest.main()
