"""The frame validator (scripts/validate_frames.py): it reads frames back the
way chart_frames.encode() wrote them, it notices a wrong number, and
Wetterzentrale's charts stay something to look at: nothing here, in the app
or in a workflow reads them for data, publishes them or uploads them.

  python -m unittest discover -s tests
"""
import glob
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import chart_frames as cf  # noqa: E402
import validate_frames as vf  # noqa: E402
from test_frames import fields  # noqa: E402


class Decode(unittest.TestCase):
    def test_reads_what_encode_wrote(self):
        P, S = 12, 9
        p, u, v, h, t = fields(P, S)
        d = vf.decode(cf.encode(p, u, v, h, t), P, S)
        np.testing.assert_allclose(d['p'], p, atol=0.5 / cf.SCALE['p'][0] + 1e-9)
        np.testing.assert_allclose(d['ux'], u, atol=0.25 + 1e-9)
        np.testing.assert_allclose(d['uy'], v, atol=0.25 + 1e-9)
        np.testing.assert_array_equal(np.isnan(d['h']), np.isnan(h))
        np.testing.assert_allclose(d['t'][~np.isnan(t)], t[~np.isnan(t)], atol=0.05 + 1e-9)

    def test_a_frame_of_the_wrong_size_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'bytes'):
            vf.decode(b'\0' * 10, 12, 9)

    def test_points_land_in_the_square(self):
        fr = dict(p=np.zeros((cf.P_N, cf.P_N)))
        for name, lat, lon in vf.POINTS:
            vf.frame_at(fr, 'p', lon, lat)


def case(**over):
    """A comparison result with ours the same as NOAA's, then changed."""
    pt = dict(point='Mid North Sea', lat=56.5, lon=2.5, p=[1000.0, 1000.0], wind=[10.0, 10.0],
              hs=[2.0, 2.0], tp=[10.0, 10.0], dir=[90.0, 90.0])
    pt.update(over)
    g = {k: dict(n=5000, bias=0, rms=0.01, p99=0.05, max=0.1, worst_at=[0, 0]) for k in ('p', 'wind', 'hs', 'tp')}
    return dict(points=[pt], grid=g)


class Problems(unittest.TestCase):
    def test_agreeing_frame_passes(self):
        self.assertEqual(vf.problems(case()), [])

    def test_pressure_in_the_wrong_units(self):
        self.assertTrue(vf.problems(case(p=[100000.0, 1000.0])))

    def test_wind_rotated_wrongly(self):
        self.assertTrue(any('blowing' in s for s in vf.problems(case(dir=[180.0, 90.0]))))

    def test_calm_wind_direction_is_not_judged(self):
        self.assertEqual(vf.problems(case(wind=[2.0, 2.0], dir=[180.0, 90.0])), [])

    def test_waves_flipped_to_nothing(self):
        self.assertTrue(vf.problems(case(hs=[float('nan'), 2.0])))

    def test_coast_fill_where_noaa_has_no_sea_is_not_a_fault(self):
        self.assertEqual(vf.problems(case(hs=[0.2, float('nan')], tp=[8.0, float('nan')])), [])

    def test_a_whole_grid_off(self):
        r = case()
        r['grid']['p']['rms'] = 5.0
        self.assertTrue(vf.problems(r))

    def test_too_few_cells_to_judge(self):
        r = case()
        r['grid']['hs']['n'] = 3
        self.assertTrue(vf.problems(r))


class CellProblems(unittest.TestCase):
    """The cell tiles against NOAA's own grid points (made-up values here)."""

    class Src:
        def __init__(self, **over):
            self.over = over

        def cell(self, cid):
            return {**dict(hs=1.23, tl=11.04, dp=359.3, p=1012.31, u=-3.1, v=4.2), **self.over}

    @staticmethod
    def ours(**over):
        # As stored: rounded to the tiles' steps (grid.py).
        return lambda cid: {**dict(hs=1.2, tl=11.0, dp=0.0, p=1012.3, u=-3.0, v=4.0), **over}

    def test_rounded_as_stored_passes(self):
        self.assertEqual(vf.cell_problems(self.ours(), self.Src()), [])

    def test_only_points_over_the_north_sea(self):
        seen = []
        vf.cell_problems(lambda cid: seen.append(cid) or self.ours()(cid), self.Src())
        self.assertIn('d4:219:-4', seen)
        self.assertEqual(len(seen), sum(1 for _, la, lo in vf.POINTS if 48 <= la < 64 and -12 <= lo < 16))

    def test_a_resampled_value_is_a_fault(self):
        found = vf.cell_problems(self.ours(hs=1.4), self.Src())
        self.assertTrue(found and all('cell hs' in f for f in found))

    def test_direction_wraps_past_north(self):
        self.assertEqual(vf.cell_problems(self.ours(dp=0.0), self.Src(dp=359.5)), [])
        self.assertTrue(vf.cell_problems(self.ours(dp=358.0), self.Src(dp=0.4)))

    def test_land_matches_land(self):
        nan = float('nan')
        self.assertEqual(vf.cell_problems(self.ours(hs=nan, tl=nan, dp=nan), self.Src(hs=nan, tl=nan, dp=nan)), [])
        self.assertTrue(vf.cell_problems(self.ours(hs=nan), self.Src()))


class WetterzentraleStaysInternal(unittest.TestCase):
    def test_pictures_are_only_written_where_git_ignores_them(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit) as e:
                vf.main(['--wetterzentrale', d, '--steps', '0'])
            self.assertIn('not ignored', str(e.exception))

    def test_the_folder_for_them_is_ignored(self):
        self.assertTrue(vf.git_ignored(os.path.join(ROOT, 'validation', 'f000.png')))

    def test_nothing_the_app_serves_mentions_it(self):
        for name in ('index.html', 'app.js', 'i18n.js', 'hints.js', 'sw.js', 'privacy.html', 'legacy.html'):
            with open(os.path.join(ROOT, name), encoding='utf-8') as f:
                self.assertNotIn('wetterzentrale.de', f.read().lower(), name)

    def test_only_the_validator_reads_it(self):
        users = [os.path.basename(p) for p in glob.glob(os.path.join(ROOT, 'scripts', '*')) + glob.glob(os.path.join(ROOT, '.github', 'workflows', '*'))
                 if os.path.isfile(p) and 'wetterzentrale.de' in open(p, encoding='utf-8').read().lower()]
        self.assertEqual(users, ['validate_frames.py'])

    def test_no_workflow_asks_for_the_pictures_or_uploads_anything_from_them(self):
        for p in glob.glob(os.path.join(ROOT, '.github', 'workflows', '*')):
            text = open(p, encoding='utf-8').read()
            self.assertNotIn('--wetterzentrale', text, p)
            if os.path.basename(p) == 'validate.yml':
                self.assertNotIn('upload-artifact', text)
                self.assertNotIn('git push', text)


if __name__ == '__main__':
    unittest.main()
