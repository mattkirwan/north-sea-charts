"""The chart app's frame format, end to end: chart_frames.py's encode() and
the app's own decode() (app.js, run under Node) must agree, value for value,
at the scales the manifest gives; and check() must refuse broken data.

  python -m unittest discover -s tests
"""
import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))
import chart_frames as cf  # noqa: E402


def app_decode(body, P, S):
    """The frame's bytes gzipped as published, read back by app.js's decode(),
    and turned into hPa, m/s, m and s the way the app does (NaN for 255)."""
    with tempfile.NamedTemporaryFile(suffix='.bin.gz', delete=False) as f:
        f.write(gzip.compress(body, 9))
    try:
        out = subprocess.run(['node', os.path.join(HERE, 'decode_frame.cjs'), f.name, str(P), str(S)],
                             check=True, capture_output=True, text=True).stdout
    finally:
        os.unlink(f.name)
    d = {k: np.array(v, dtype=np.float64) for k, v in json.loads(out).items()}
    (ps, pb), sc = cf.SCALE['p'], cf.SCALE
    sea = lambda q, k: np.where(q == 255, np.nan, q / k).reshape(S, S)
    return dict(p=(d['p'] / ps + pb).reshape(P, P), u=(d['u'] / sc['wind']).reshape(P, P),
                v=(d['v'] / sc['wind']).reshape(P, P), h=sea(d['h'], sc['h']), t=sea(d['t'], sc['t']))


def fields(P, S, seed=0):
    """Plausible fields with the awkward values in: the pressure limits, steep
    jumps along a row (the row deltas wrap), calm and gale winds both ways,
    land (NaN), flat calm and the biggest seas."""
    rng = np.random.default_rng(seed)
    p = rng.uniform(870, 1095, (P, P))
    p[0, :3] = [870, 1095, 870]
    u, v = rng.uniform(-60, 60, (P, P)), rng.uniform(-60, 60, (P, P))
    h, t = rng.uniform(0, 25, (S, S)), rng.uniform(1, 25, (S, S))
    h[0, :4] = [0, 25, 0, 25]
    land = rng.random((S, S)) < 0.3
    h[land], t[land] = np.nan, np.nan
    return p, u, v, h, t


class RoundTrip(unittest.TestCase):
    def check_round_trip(self, P, S, seed=0):
        p, u, v, h, t = fields(P, S, seed)
        d = app_decode(cf.encode(p, u, v, h, t), P, S)
        (ps, _), sc = cf.SCALE['p'], cf.SCALE
        # Each value comes back within half a step of what was stored.
        np.testing.assert_allclose(d['p'], p, atol=0.5 / ps + 1e-9)
        np.testing.assert_allclose(d['u'], u, atol=0.5 / sc['wind'] + 1e-9)
        np.testing.assert_allclose(d['v'], v, atol=0.5 / sc['wind'] + 1e-9)
        for got, want, k in ((d['h'], h, sc['h']), (d['t'], t, sc['t'])):
            np.testing.assert_array_equal(np.isnan(got), np.isnan(want))
            np.testing.assert_allclose(got[~np.isnan(want)], want[~np.isnan(want)], atol=0.5 / k + 1e-9)

    def test_small_grids(self):
        self.check_round_trip(7, 9)

    def test_published_grid_sizes(self):
        self.check_round_trip(cf.P_N, cf.S_N, seed=1)

    def test_frame_size(self):
        p, u, v, h, t = fields(cf.P_N, cf.S_N)
        self.assertEqual(len(cf.encode(p, u, v, h, t)), 4 * cf.P_N ** 2 + 2 * cf.S_N ** 2)

    def test_out_of_range_values_clip_rather_than_wrap(self):
        P, S = 3, 3
        p = np.full((P, P), 1000.0)
        u = np.array([[100.0, -100.0, 0]] * P)              # past int8 at 2 per m/s
        h = np.array([[40.0, -1.0, np.nan]] * S)            # past 25.4 m; below 0; land
        t = np.array([[40.0, 5.0, np.nan]] * S)
        d = app_decode(cf.encode(p, u, u, h, t), P, S)
        np.testing.assert_allclose(d['u'][0], [63.5, -63.5, 0])
        np.testing.assert_allclose(d['h'][0], [25.4, 0, np.nan])
        np.testing.assert_allclose(d['t'][0], [25.4, 5.0, np.nan])


class Checks(unittest.TestCase):
    def good(self):
        p, u, v, h, t = fields(cf.P_N, cf.S_N)
        return [p, u, v, h, t]

    def test_plausible_frame_passes(self):
        cf.check(0, *self.good())

    def refused(self, i, value):
        f = self.good()
        f[i] = value(f[i])
        with self.assertRaises(RuntimeError):
            cf.check(0, *f)

    def test_pressure_missing(self):
        self.refused(0, lambda p: np.where(np.arange(p.size).reshape(p.shape) == 5, np.nan, p))

    def test_pressure_in_pascals(self):
        self.refused(0, lambda p: p * 100)

    def test_wind_missing(self):
        self.refused(1, lambda u: np.full_like(u, np.nan))

    def test_wind_impossible(self):
        self.refused(2, lambda v: v + 200)

    def test_waves_all_missing(self):
        self.refused(3, lambda h: np.full_like(h, np.nan))

    def test_period_all_missing(self):
        self.refused(4, lambda t: np.full_like(t, np.nan))

    def test_waves_impossible(self):
        self.refused(3, lambda h: h + 30)


class ManifestContract(unittest.TestCase):
    def test_app_reads_the_wind_scale_it_is_given(self):
        # The app once divided wind by a fixed 2; it must use the manifest's.
        with open(os.path.join(HERE, '..', 'app.js')) as f:
            src = f.read()
        self.assertIn('man.scale.wind', src)
        self.assertNotRegex(src, r'bilinear\(d\.[uv], P, gj, gi\) / 2\b')

    def test_run_folder(self):
        import datetime as dt
        self.assertEqual(cf.run_dir(dt.datetime(2026, 10, 27, 6)), '2026-10-27-06z')


if __name__ == '__main__':
    unittest.main()
