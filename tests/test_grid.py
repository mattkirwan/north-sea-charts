"""The grid (scripts/grid.py, and grid.js in the app): cells named for NOAA's
own grid points, for keeps; the cell tiles the frames job writes, read back
by Python and by the app under Node, value for value; and the app's square
projected the same way on both sides.

  python -m unittest discover -s tests
"""
import base64
import datetime as dt
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))
import chart_frames as cf  # noqa: E402
import grid  # noqa: E402

RUN = dt.datetime(2026, 10, 29, 6)
STEPS = [0, 1, 2, 3, 6]


def box_index(lat, lon):
    """A cell's place in the box (grid.cut()'s rows and columns)."""
    return int(round((grid.CELL_BOX['n'] - 0.25 - lat) * 4)), int(round((lon - grid.CELL_BOX['w']) * 4))


def fake_boxes(steps, seed=0):
    """What frame() hands back for each step over the box: plausible values,
    the awkward ones in (no sea, gales both ways, the pressure limits, the
    direction wrapping past north), and a known coast off Saltburn: its own
    cell (54.50N 1.00W) and the ones round it land, but for the wave model's
    cell north of it; and stretches of open sea in the Norwegian and North Seas."""
    rng = np.random.default_rng(seed)
    rows, cols = grid.box_shape()
    land = rng.random((rows, cols)) < 0.3
    land[0, :3] = False
    i, j = box_index(54.5, -1.0)
    land[i - 4:i + 5, j - 4:j + 5] = True                 # the coast round Saltburn
    land[box_index(54.75, -1.0)] = False
    for (n, w), (s, e) in ((box_index(70.0, 0.0), box_index(64.0, 8.0)), (box_index(57.0, 1.0), box_index(55.5, 4.0))):
        land[n:s + 1, w:e + 1] = False                    # open sea in the Norwegian Sea and the North Sea
    out = {}
    for k, s in enumerate(steps):
        b = dict(hs=rng.uniform(0, 25, (rows, cols)), tp=rng.uniform(1, 25, (rows, cols)), tl=rng.uniform(1, 25, (rows, cols)),
                 dl=rng.uniform(0, 360, (rows, cols)), dp=rng.uniform(0, 360, (rows, cols)),
                 u=rng.uniform(-60, 60, (rows, cols)), v=rng.uniform(-60, 60, (rows, cols)), p=rng.uniform(870, 1095, (rows, cols)))
        b['hs'][0, :3], b['dl'][0, :3], b['p'][0, :3] = [0, 25, 1.25], [359.2, 0.4, 181], [870, 1095, 1013.25]
        b['hs'][box_index(54.75, -1.0)] = 1.0 + k / 10
        for key in ('hs', 'tp', 'tl', 'dl', 'dp'):
            b[key][land] = np.nan
        out[s] = {key: v.astype(np.float32) for key, v in b.items()}
    return out


def js(ask):
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump(ask, f)
    try:
        out = subprocess.run(['node', os.path.join(HERE, 'grid_parity.cjs'), f.name], check=True, capture_output=True, text=True).stdout
    finally:
        os.unlink(f.name)
    return json.loads(out)


class Cells(unittest.TestCase):
    def test_saltburn(self):
        # The wave model's cell nearest Saltburn, as gfs_charts.py has it (read
        # from the source: the chart job's own requirements aren't the tests').
        import ast
        with open(os.path.join(HERE, '..', 'scripts', 'gfs_charts.py')) as f:
            cell = next(ast.literal_eval(n.value) for n in ast.parse(f.read()).body
                        if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'SALTBURN_CELL')
        self.assertEqual(grid.cell_id(*cell), 'd4:219:-4')
        self.assertEqual(grid.cell_of('d4:219:-4'), (54.75, -1.0))

    def test_a_cell_is_the_area_round_its_point(self):
        self.assertEqual(grid.cell_id(54.70, -0.90), 'd4:219:-4')
        self.assertEqual(grid.cell_id(54.874, -1.124), 'd4:219:-4')
        self.assertEqual(grid.cell_bounds('d4:219:-4'), (54.625, 54.875, -1.125, -0.875))

    def test_edges_go_north_and_east(self):
        # Not Python's round(), which would send 54.625 south (218.5 to even).
        self.assertEqual(grid.cell_id(54.625, -1.125), 'd4:219:-4')
        self.assertEqual(grid.cell_id(-0.125, -0.125), 'd4:0:0')

    def test_longitude_wraps(self):
        self.assertEqual(grid.cell_id(60, 180), 'd4:240:-720')
        self.assertEqual(grid.cell_id(60, 359.75), grid.cell_id(60, -0.25))
        self.assertEqual(grid.cell_id(60, 179.9), 'd4:240:-720')

    def test_finer_grids_are_named_apart(self):
        self.assertEqual(grid.cell_id(54.75, -1.0, 12), 'd12:657:-12')
        self.assertIsNone(grid.tile_of('d12:657:-12'))

    def test_not_cells(self):
        for bad in ('x4:1:1', 'd4:1', 'd0:1:1', 'd4:361:0', 'd4:0:720', 'd4:a:1'):
            with self.assertRaises(ValueError, msg=bad):
                grid.parse(bad)

    def test_round_trip(self):
        rng = np.random.default_rng(3)
        for lat, lon in zip(rng.uniform(-89, 89, 200), rng.uniform(-180, 180, 200)):
            cid = grid.cell_id(lat, lon)
            s, n, w, e = grid.cell_bounds(cid)
            self.assertTrue(s <= lat < n + 1e-9 and (w <= lon < e + 1e-9 or w <= lon + 360 < e + 1e-9), (lat, lon, cid))
            self.assertEqual(grid.cell_id(*grid.cell_of(cid)), cid)


class Tiles(unittest.TestCase):
    def test_tiles_cover_the_box(self):
        names = grid.tile_names()
        self.assertEqual(len(names), 240)
        self.assertEqual(names[0], '84_-56')
        self.assertEqual(names[-1], '48_36')
        self.assertEqual(grid.tile_of('d4:219:-4'), '52_-4')
        coarse = grid.tile_names(grid.COARSE)                    # the open sea's d1 tiles: 8° square
        self.assertEqual((len(coarse), coarse[0], coarse[-1]), (60, '80_-56', '48_32'))
        self.assertEqual(grid.tile_of('d1:55:2'), '48_0')

    def test_box_edges(self):
        self.assertEqual(grid.tile_of(grid.cell_id(48.0, -56.0)), '48_-56')
        self.assertEqual(grid.tile_of(grid.cell_id(87.75, 39.75)), '84_36')
        for lat, lon in ((47.75, 0), (88.0, 0), (55, -56.25), (55, 40.0)):
            self.assertIsNone(grid.tile_of(grid.cell_id(lat, lon)), (lat, lon))
        self.assertEqual(grid.tile_of('d1:87:39'), '80_32')
        self.assertIsNone(grid.tile_of('d1:47:0'))
        self.assertIsNone(grid.tile_of('d12:657:-12'))

    def test_split_and_find(self):
        rows, cols = grid.box_shape()
        lat = (grid.CELL_BOX['n'] - 0.25 - np.arange(rows) / 4)[:, None] + 0 * np.arange(cols)
        lon = (grid.CELL_BOX['w'] + np.arange(cols) / 4)[None, :] + 0 * np.arange(rows)[:, None]
        box = dict(lat=lat[None], lon=lon[None])
        t = grid.tiles(box)
        for la, lo in ((54.75, -1.0), (48.0, -56.0), (87.75, 39.75), (60.0, 4.0), (59.75, 3.75)):
            cid = grid.cell_id(la, lo)
            name = grid.tile_of(cid)
            i, j = grid.tile_cell(name, cid)
            self.assertEqual((t[name]['lat'][0, i, j], t[name]['lon'][0, i, j]), (la, lo))
        # The open sea's d1 tiles: the box's whole-degree points.
        t = grid.tiles(box, grid.COARSE)
        for la, lo in ((55, 2), (48, -56), (87, 39), (64, -8)):
            cid = grid.cell_id(la, lo, grid.COARSE)
            name = grid.tile_of(cid)
            i, j = grid.tile_cell(name, cid)
            self.assertEqual((t[name]['lat'][0, i, j], t[name]['lon'][0, i, j]), (la, lo))

    def test_cut_from_noaas_grid(self):
        # A field on the frames' AREA cut of the 0.25° grid, holding its own lat and lon.
        lats = np.arange(cf.AREA['n'], cf.AREA['s'] - 0.01, -0.25)
        lons = np.arange(cf.AREA['w'], cf.AREA['e'] + 0.01, 0.25)
        c = grid.cut(lats[:, None] + 0 * lons, lats[0], lons[0])
        d = grid.cut(0 * lats[:, None] + lons, lats[0], lons[0])
        self.assertEqual(c.shape, grid.box_shape())
        self.assertEqual((c[0, 0], d[0, 0], c[-1, -1], d[-1, -1]), (87.75, -56.0, 48.0, 39.75))
        # As NOAA's GRIBs give it (2026-10-28 00z): close enough to be on the cells.
        np.testing.assert_array_equal(grid.cut(lats[:, None] + 0 * lons, lats[0], -79.99998754690796), c)
        with self.assertRaises(ValueError):
            grid.cut(c, 88.1, -80)
        with self.assertRaises(ValueError):
            grid.cut(c[:10], 87.75, -56)

    def test_round_trip(self):
        t = {k: v[:, :16, :16] for k, v in {k: np.stack([b[k] for b in fake_boxes(STEPS).values()])
                                            for k, _ in grid.VARS}.items()}
        body = grid.encode_tile(t)
        self.assertEqual(len(body), grid.tile_size(len(STEPS)))
        d = grid.decode_tile(body, len(STEPS))
        for k, half in (('hs', 0.05), ('tp', 0.05), ('tl', 0.05), ('u', 0.25), ('v', 0.25), ('p', 0.025)):
            np.testing.assert_array_equal(np.isnan(d[k]), np.isnan(t[k]), k)
            ok = ~np.isnan(t[k])
            np.testing.assert_allclose(d[k][ok], np.clip(t[k][ok], -63.5 if k in 'uv' else 0, 25.4 if k in ('hs', 'tp', 'tl') else 9e9),
                                       atol=half + 1e-4, err_msg=k)
        for k in ('dl', 'dp'):
            ok = ~np.isnan(t[k])
            self.assertTrue(np.all(np.abs((d[k][ok] - t[k][ok] + 180) % 360 - 180) <= 1 + 1e-4), k)
        self.assertEqual(list(d['dl'][0, 0, :2]), [0, 0])         # 359.2° and 0.4°: north, not 360

    def test_a_tile_of_the_wrong_size_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'bytes'):
            grid.decode_tile(b'\0' * 100, 3)


class Swell(unittest.TestCase):
    def test_longest_swell_and_its_direction(self):
        nan = np.nan
        f = lambda *v: (np.array([v], dtype=float), 88.0, -80.0)
        w = dict(hs=f(2.0, 1.0, 0.5, nan), tp=f(8.0, 6.0, 5.0, nan), dp=f(30.0, 40.0, 50.0, nan),
                 sh1=f(1.0, 0.05, 0.05, nan), sp1=f(9.0, 14.0, 9.0, nan), sd1=f(10.0, 20.0, 30.0, nan),
                 sh2=f(0.3, 0.5, 0.05, nan), sp2=f(15.0, 7.0, 9.0, nan), sd2=f(300.0, 310.0, 320.0, nan),
                 sh3=f(nan, nan, nan, nan), sp3=f(nan, nan, nan, nan), sd3=f(nan, nan, nan, nan))
        tl, dl = cf.longest_swell(w)
        # The 15 s swell; the 7 s one (the 14 s is under 0.1 m); only wind sea; land.
        np.testing.assert_array_equal(tl[0], [15.0, 7.0, 5.0, nan])
        np.testing.assert_array_equal(dl[0], [300.0, 310.0, 50.0, nan])


class Written(unittest.TestCase):
    """cell_tiles() as the frames job runs it, then read by grid.py and grid.js."""

    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        cls.boxes = fake_boxes(STEPS)
        cls.entry = cf.cell_tiles(cls.out, RUN, STEPS, cls.boxes)
        sq = dict(x0=cf.X0, x1=cf.X1, y0=cf.Y0, y1=cf.Y1, proj=cf.PROJ4)
        cls.manifest = dict(run=1793253600000, steps=STEPS, square=sq, cells=cls.entry)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out)

    def tile(self, name, n=grid.LATTICE):
        sub = '' if n == grid.LATTICE else 'd1'
        with open(os.path.join(self.out, self.entry['dir'], sub, f'{name}.bin.gz'), 'rb') as f:
            return grid.decode_tile(gzip.decompress(f.read()), len(STEPS), grid.tile_side(n))

    def unbits(self, b64, n=grid.LATTICE):
        rows, cols = grid.box_shape(n)
        return np.unpackbits(np.frombuffer(base64.b64decode(b64), np.uint8))[:rows * cols].reshape(rows, cols).astype(bool)

    def test_manifest_entry(self):
        self.assertEqual(self.entry['dir'], 'cells/2026-10-29-06z/5')
        self.assertEqual(self.entry['encoding'], 'cell-series-v1')
        self.assertIn('52_-4', self.entry['tiles'])
        # Only the tiles with beacon points, d4 and d1 (in its own folder).
        d = os.path.join(self.out, self.entry['dir'])
        self.assertEqual(sorted(os.listdir(d)), sorted([f'{n}.bin.gz' for n in self.entry['tiles']] + ['d1']))
        c = self.entry['coarse']
        self.assertEqual((c['lattice'], c['tile'], c['file']), (1, 8, '{dir}/d1/{tile}.bin.gz'))
        self.assertEqual(sorted(os.listdir(os.path.join(d, 'd1'))), sorted(f'{n}.bin.gz' for n in c['tiles']))
        fine, open_sea = self.unbits(self.entry['points']), self.unbits(c['points'], grid.COARSE)
        self.assertEqual(set(self.entry['tiles']), set(grid.tiles_with(fine)))
        self.assertEqual(set(c['tiles']), set(grid.tiles_with(open_sea, grid.COARSE)))

    def test_the_beacon_points(self):
        box = {k: np.stack([self.boxes[s][k] for s in STEPS]) for k, _ in grid.VARS}
        fine, open_sea = grid.beacon_points(box)
        np.testing.assert_array_equal(self.unbits(self.entry['points']), fine)
        np.testing.assert_array_equal(self.unbits(self.entry['coarse']['points'], grid.COARSE), open_sea)
        sea = np.isfinite(box['hs']).any(axis=0)
        self.assertTrue(fine[box_index(54.75, -1.0)])                # the wave model's cell off Saltburn, by the coast
        self.assertFalse(fine[box_index(54.5, -1.0)])                # land
        lat, lon = grid.box_latlon()
        area = grid.beacon_area(lat, lon)
        self.assertFalse((fine & ~(sea & area)).any())              # sea in the area only
        self.assertFalse(area[box_index(57.0, -8.0)])                # west of Scotland: no
        self.assertTrue(area[box_index(55.0, 2.0)])                  # the open North Sea: yes
        self.assertTrue(area[box_index(76.0, 14.0)])                 # off Svalbard: yes, though out of the window
        self.assertTrue(area[box_index(70.0, 19.0)])                 # off Tromsø: yes
        self.assertFalse(grid.window_mask(lat, lon)[box_index(70.0, 19.0)])
        self.assertFalse(area[box_index(71.25, 25.75)])              # round the top past 70.66N 21.93E: no
        self.assertFalse(area[box_index(64.0, 21.0)])                # the Gulf of Bothnia: no
        self.assertTrue(area[box_index(67.0, 13.0)])                 # off Bodø: yes
        self.assertFalse(area[box_index(58.0, 20.0)])                # the Baltic: no
        self.assertFalse(area[box_index(77.5, 22.0)])                # Svalbard's east coast: no
        self.assertFalse(area[box_index(73.0, 28.0)])                # the Barents Sea: no
        self.assertFalse(area[box_index(58.0, 9.0)])                 # the Skagerrak: no
        self.assertFalse(area[box_index(57.0, 11.5)])                # the Kattegat: no
        self.assertTrue(area[box_index(56.0, 8.0)])                  # off Jutland's North Sea coast: yes
        self.assertTrue(area[box_index(58.0, 5.5)])                  # off Norway's south-west coast: yes
        # Out at sea, every other whole degree only, none by the coast; in the
        # North Sea, d4 points every half degree instead.
        c_lat, c_lon = grid.coarse(lat), grid.coarse(lon)
        self.assertTrue(open_sea.any())
        self.assertTrue(((c_lat[open_sea] % 2 == 0) & (c_lon[open_sea] % 2 == 0)).all())
        D = grid.DENSE
        dense = lambda la, lo: (la >= D['s']) & (la <= D['n']) & (lo >= D['w']) & (lo <= D['e'])
        self.assertFalse((open_sea & dense(c_lat, c_lon)).any())
        far = fine & ~grid.near_land(sea, grid.COAST_KM)
        self.assertTrue(far.any())
        self.assertTrue((dense(lat, lon) & (lat * 4 % 2 == 0) & (lon * 4 % 2 == 0))[far].all())
        # A lone cell with no sea isn't coast: open sea all round it.
        one = dict(hs=np.ones((1,) + lat.shape))
        one['hs'][0][box_index(66.0, 3.0)] = np.nan
        f1, o1 = grid.beacon_points(one)
        self.assertFalse((f1 & ~dense(lat, lon)).any())
        at = lambda la, lo: o1[grid.coarse(np.arange(lat.size).reshape(lat.shape)) == np.ravel_multi_index(box_index(la, lo), lat.shape)]
        self.assertTrue(at(66.0, 4.0).all())
        # Out in the Atlantic, two rows of them south of the window.
        self.assertFalse(grid.beacon_area(lat, lon)[box_index(52.0, -30.0)])
        self.assertTrue(at(52.0, -30.0).all())
        self.assertFalse(at(50.0, -30.0).any())
        self.assertFalse((grid.coarse(fine) & open_sea).any())
        # And the app reads the same points, without a tile.
        got = js(dict(manifest=self.manifest, base=self.out + '/'))
        self.assertEqual(got['asked'], [])
        want = [f'd4:{grid.LATTICE * grid.CELL_BOX["n"] - 1 - i}:{grid.LATTICE * grid.CELL_BOX["w"] + j}' for i, j in zip(*np.nonzero(fine))]
        want += [f'd1:{grid.CELL_BOX["n"] - 1 - i}:{grid.CELL_BOX["w"] + j}' for i, j in zip(*np.nonzero(open_sea))]
        self.assertEqual(got['sea'], want)

    def test_a_cell_keeps_its_own_numbers(self):
        t = self.tile('52_-4')
        i, j = grid.tile_cell('52_-4', 'd4:219:-4')
        np.testing.assert_allclose(t['hs'][:, i, j], [1.0, 1.1, 1.2, 1.3, 1.4])
        bi = box_index(54.75, -1.0)
        np.testing.assert_allclose(t['p'][:, i, j], [self.boxes[s]['p'][bi] for s in STEPS], atol=0.026)

    def test_no_tiles_without_the_numbers(self):
        out = tempfile.mkdtemp()
        try:
            self.assertIsNone(cf.cell_tiles(out, RUN, STEPS, {**self.boxes, 2: None}))
            self.assertIsNone(cf.cell_tiles(out, RUN, STEPS, {0: self.boxes[0]}))
        finally:
            shutil.rmtree(out)

    def test_app_reads_them_the_same(self):
        rows, cols = grid.box_shape(grid.COARSE)
        i, j = np.argwhere(self.unbits(self.entry['coarse']['points'], grid.COARSE))[0]
        out_at_sea = f'd1:{grid.CELL_BOX["n"] - 1 - i}:{grid.CELL_BOX["w"] + j}'
        ids = ['d4:219:-4', 'd4:218:-4', 'd4:192:-48', 'd4:255:63', 'd4:240:4', 'd4:100:0', out_at_sea]
        got = js(dict(manifest=self.manifest, base=self.out + '/', series=ids, ids=ids,
                      resolve=[[54.58, -0.97, 'waves'], [54.58, -0.97, 'wind'], [30.0, 0.0, 'waves']]))
        written = lambda cid: grid.tile_of(cid) in (self.entry['tiles'] if cid.startswith('d4:') else self.entry['coarse']['tiles'])
        for cid, s in zip(ids, got['series']):
            name = grid.tile_of(cid)
            if not written(cid):
                self.assertIsNone(s, cid)
                continue
            t = self.tile(name, grid.parse(cid)[0])
            i, j = grid.tile_cell(name, cid)
            self.assertEqual((s['id'], s['lat'], s['lon'], s['steps']), (cid, *grid.cell_of(cid), STEPS))
            self.assertEqual(s['sea'], bool(np.isfinite(t['hs'][:, i, j]).any()), cid)
            for k, _ in grid.VARS:
                want = [None if np.isnan(x) else float(x) for x in t[k][:, i, j]]
                np.testing.assert_allclose(np.array(s[k], dtype=float), np.array(want, dtype=float), rtol=1e-6, atol=1e-6, err_msg=f'{cid} {k}')
        self.assertFalse(got['series'][1]['sea'])                  # Saltburn's own cell is land: wind and pressure only
        self.assertTrue(np.isnan(np.array(got['series'][1]['hs'], dtype=float)).all())
        self.assertTrue(np.isfinite(np.array(got['series'][1]['u'], dtype=float)).all())
        waves, wind, nowhere = got['resolved']
        self.assertEqual(waves['id'], 'd4:219:-4')                 # the sea cell north of the beach
        self.assertAlmostEqual(waves['km'], 19.0, delta=1.5)
        self.assertLess(abs(waves['bearing'] - 354), 2)          # a little west of north
        self.assertEqual(wind, dict(id='d4:218:-4', km=0, bearing=0))
        self.assertIsNone(nowhere)
        self.assertTrue(all(u.endswith(f'?run={self.manifest["run"]}') for u in got['asked']))
        self.assertEqual(got['tiles'], [grid.tile_of(c) if written(c) else None for c in ids])


class Square(unittest.TestCase):
    def test_app_projects_as_the_frames_do(self):
        rng = np.random.default_rng(5)
        pts = [[54.75, -1.0], [88.0, 0.0], [35.0, -80.0], [70.0, 60.0], [60.0, 179.0], [45.0, -170.0]]
        pts += [[float(a), float(b)] for a, b in zip(rng.uniform(35, 89, 50), rng.uniform(-180, 180, 50))]
        km = [[float(x), float(y)] for x, y in zip(rng.uniform(cf.X0, cf.X1, 50), rng.uniform(cf.Y1, cf.Y0, 50))]
        ids = ['d4:219:-4', 'd4:240:0']
        sq = dict(x0=cf.X0, x1=cf.X1, y0=cf.Y0, y1=cf.Y1, proj=cf.PROJ4)
        got = js(dict(manifest=dict(run=0, steps=[0], square=sq, cells=None), points=pts, km=km, ids=ids,
                      bad=['d4:1', 'x4:1:1', 'd4:999:0', 'd4:219:-4']))
        for (lat, lon), (x, y) in zip(pts, got['km']):
            np.testing.assert_allclose([x, y], grid.FWD(lon, lat), atol=1e-6)
        for (x, y), (lon, lat) in zip(km, got['lonlat']):
            plon, plat = grid.INV(x, y)
            self.assertAlmostEqual(lat, plat, places=9)
            self.assertAlmostEqual((lon - plon + 180) % 360 - 180, 0, places=9)
        self.assertEqual(got['cells'], [grid.cell_id(lat, lon) for lat, lon in pts])
        self.assertEqual(got['tiles'], [None, None])               # no cells in this manifest
        s, n, w, e = grid.cell_bounds('d4:219:-4')
        corners = np.array(got['bounds'][0]).reshape(-1, 2)
        np.testing.assert_allclose(corners[0], grid.FWD(w, n), atol=1e-6)
        np.testing.assert_allclose(corners[4], grid.FWD(e, s), atol=1e-6)
        self.assertEqual(got['bad'], [True, True, True, False])

    def test_edges_agree(self):
        pts = [[54.625, -1.125], [-0.125, -0.125], [60.0, 180.0], [60.0, -180.0], [12.375, 7.875]]
        sq = dict(x0=cf.X0, x1=cf.X1, y0=cf.Y0, y1=cf.Y1, proj=cf.PROJ4)
        got = js(dict(manifest=dict(run=0, steps=[0], square=sq), points=pts))
        self.assertEqual(got['cells'], [grid.cell_id(lat, lon) for lat, lon in pts])


if __name__ == '__main__':
    unittest.main()
