"""The grid: where every number the app shows sits on the Earth.

Two kinds of grid, kept apart on purpose:

The cells are NOAA's own. GFS and GFS-Wave both run on the same 0.25° grid
of latitude and longitude, and a value there is what the model computed, not
something we've blended. A cell is named for its grid point, d<N>:<row>:<col>,
N cells to the degree, row = lat * N, col = lon * N (lon from -180 to 180):
the wave model's cell off Saltburn, 54.75N 1.00W, is d4:219:-4. A cell is
the area within half a cell of its point. The names are for keeps: links,
saved spots and alerts may hold them, so a cell's name never changes meaning.
A finer grid from NOAA one day is a new N (d6, d12), beside d4, not a
renumbering. Things that belong to a place (a beach, an alert) are better
kept as latitude and longitude and resolved to the best cell when used
(grid.js's resolve()), so a finer grid improves them for free.

The square is the chart's: polar stereographic on the Greenwich meridian,
about 4,600 km a side, which the frames (chart_frames.py) resample the model
onto for the app to draw: 185 nodes across for the swell (25 km), 116 for
pressure and wind (40 km). It's a picture of the model, so nothing keeps
its node numbers.

Over the North Sea and its approaches (CELL_BOX), the frames job also writes
each cell's values over the whole run, in tiles of TILE x TILE cells (4°
square, on whole multiples of 4°), one gzipped file a tile, named for its
south-west cell (52_-4: 52.00 to 55.75N, 4.00 to 0.25W). The app takes a
tile when it wants a place's forecast (grid.js); a run's tiles are kept, so
the cells' history builds up. Each tile, cell-series-v1, is in VARS order:
for each variable, the cells row by row (north to south, west to east), and
each cell's values step by step, stored as the differences from one step to
the next (modulo 256, or 65536 for pressure, low bytes then high), which gzip
packs tight:

  hs  uint8   significant wave height, m * 10       (255 = no sea)
  tp  uint8   peak period, s * 10                   (255 = no sea)
  tl  uint8   period of the longest swell, s * 10   (255 = no sea)
  dl  uint8   direction the longest swell comes from, 2° steps (255 = no sea)
  dp  uint8   direction the peak waves come from, 2° steps     (255 = no sea)
  u   int8    10 m wind towards the east, m/s * 2   (-128 = none)
  v   int8    10 m wind towards the north, m/s * 2  (-128 = none)
  p   uint16  sea-level pressure, (hPa - 850) * 20  (65535 = none)

The longest swell is the longest of the model's separate swells of 0.1 m or
more, the same as the frames' period, with its own direction, so the two
always describe one swell; where there's only wind sea, the peak's. Land has
wind and pressure, and no sea.

numpy only, so the app's tests can import it.
"""
import math

import numpy as np

PROJ4 = '+proj=stere +lat_0=90 +lat_ts=60 +lon_0=0 +R=6371229 +units=km'
X0, X1, Y0, Y1 = -2805.0, 1795.0, -650.0, -5250.0   # km: west, east, north, south
P_N = 116                                          # pressure and wind: ~40 km
S_N = 185                                          # swell: 25 km
R = 6371.229

LATTICE = 4                                        # NOAA's cells to the degree
TILE = 16                                          # a tile's cells a side: 4°
CELL_BOX = dict(s=48, n=64, w=-12, e=16)           # degrees, on whole tiles
VARS = [('hs', 'u1'), ('tp', 'u1'), ('tl', 'u1'), ('dl', 'u1'), ('dp', 'u1'), ('u', 'i1'), ('v', 'i1'), ('p', 'u2')]
CELL_SCALE = dict(hs=10, tp=10, tl=10, dir=2, wind=2, p=[20, 850])   # the manifest's cells.scale
ENCODING = 'cell-series-v1'


# ---- The square --------------------------------------------------------------------------

def _stere():
    """Forward and inverse polar stereographic (north, lon 0, true at 60°N), km."""
    k0 = (1 + np.sin(np.radians(60))) / 2

    def inv(x, y):
        rho = np.hypot(x, y)
        c = 2 * np.arctan(rho / (2 * R * k0))
        lat = np.degrees(np.arcsin(np.cos(c)))
        lon = np.degrees(np.arctan2(x, -y))
        return lon, lat

    def fwd(lon, lat):
        lam, phi = np.radians(lon), np.radians(lat)
        rho = 2 * R * k0 * np.tan(np.pi / 4 - phi / 2)
        return rho * np.sin(lam), -rho * np.cos(lam)
    return fwd, inv


FWD, INV = _stere()


def nodes(n):
    """The square's n x n nodes as lon/lat: x west to east, y north to south."""
    xs, ys = np.linspace(X0, X1, n), np.linspace(Y0, Y1, n)
    gx, gy = np.meshgrid(xs, ys)
    return INV(gx, gy)


# ---- Cells -------------------------------------------------------------------------------

def cell_id(lat, lon, n=LATTICE):
    """The cell a point is in. A point on an edge goes north or east, the
    same in grid.js (half up, not Python's round(), which rounds to even)."""
    row = math.floor(lat * n + 0.5)
    col = math.floor(((lon + 180) % 360 - 180) * n + 0.5)
    if col == 180 * n:
        col = -col
    return f'd{n}:{row}:{col}'


def parse(cid):
    """(n, row, col) from a cell's name; ValueError if it isn't one."""
    d, row, col = cid.split(':')
    if d[0] != 'd':
        raise ValueError(f'not a cell: {cid}')
    n, row, col = int(d[1:]), int(row), int(col)
    if n < 1 or abs(row) > 90 * n or not -180 * n <= col < 180 * n:
        raise ValueError(f'not a cell: {cid}')
    return n, row, col


def cell_of(cid):
    """The cell's grid point: (lat, lon)."""
    n, row, col = parse(cid)
    return row / n, col / n


def cell_bounds(cid):
    """The cell's edges: (south, north, west, east), degrees."""
    n, row, col = parse(cid)
    h = 0.5 / n
    return row / n - h, row / n + h, col / n - h, col / n + h


# ---- Tiles -------------------------------------------------------------------------------

def tile_of(cid):
    """The name of the tile a cell is in (52_-4), or None outside CELL_BOX."""
    n, row, col = parse(cid)
    if n != LATTICE:
        return None
    tr, tc = row // TILE, col // TILE
    lat0, lon0 = tr * TILE // n, tc * TILE // n
    if not (CELL_BOX['s'] <= lat0 < CELL_BOX['n'] and CELL_BOX['w'] <= lon0 < CELL_BOX['e']):
        return None
    return f'{lat0}_{lon0}'


def tile_names():
    """Every tile in CELL_BOX, north to south, west to east."""
    deg = TILE // LATTICE
    return [f'{lat}_{lon}' for lat in range(CELL_BOX['n'] - deg, CELL_BOX['s'] - 1, -deg)
            for lon in range(CELL_BOX['w'], CELL_BOX['e'], deg)]


def box_shape():
    """The box's cells: (rows, cols)."""
    return (CELL_BOX['n'] - CELL_BOX['s']) * LATTICE, (CELL_BOX['e'] - CELL_BOX['w']) * LATTICE


def cut(field, lat0, lon0, step=0.25):
    """The box's cells of a field on NOAA's grid (rows from lat0 north, columns
    from lon0 west, `step` apart): rows north to south, columns west to east."""
    rows, cols = box_shape()
    i0 = (lat0 - (CELL_BOX['n'] - 1 / LATTICE)) / step
    j0 = (CELL_BOX['w'] - lon0) / step
    # NOAA's GRIBs give longitudes like -79.99998754690796: a hundredth of a
    # cell is close enough to be on it.
    if abs(i0 - round(i0)) > 0.01 or abs(j0 - round(j0)) > 0.01 or abs(step * LATTICE - 1) > 1e-9:
        raise ValueError(f'the field is not on the cells ({lat0}N {lon0}E, {step}°)')
    i0, j0 = int(round(i0)), int(round(j0))
    out = field[i0:i0 + rows, j0:j0 + cols]
    if out.shape != (rows, cols):
        raise ValueError(f'the field does not cover the box ({lat0}N {lon0}E, {field.shape})')
    return out


def tiles(box):
    """Split the box's series ({var: (steps, rows, cols)}, as cut()) into
    {tile name: {var: (steps, TILE, TILE)}}."""
    rows, _ = box_shape()
    deg = TILE // LATTICE
    out = {}
    for name in tile_names():
        lat, lon = map(int, name.split('_'))
        i = rows - (lat - CELL_BOX['s'] + deg) * LATTICE
        j = (lon - CELL_BOX['w']) * LATTICE
        out[name] = {k: a[:, i:i + TILE, j:j + TILE] for k, a in box.items()}
    return out


def tile_cell(name, cid):
    """A cell's (row, column) within its tile, north-west first."""
    n, row, col = parse(cid)
    lat, lon = map(int, name.split('_'))
    return (lat * n + TILE - 1) - row, col - lon * n


def encode_tile(t):
    """A tile's bytes before gzip ({var: (steps, TILE, TILE)}, NaN where missing)."""
    s = CELL_SCALE
    sea = lambda x, k: np.where(np.isfinite(x), np.clip(np.round(x * k), 0, 254), 255)
    deg = lambda x: np.where(np.isfinite(x), np.round(np.nan_to_num(x) / s['dir']) % (360 // s['dir']), 255)
    wind = lambda x: np.where(np.isfinite(x), np.clip(np.round(np.nan_to_num(x) * s['wind']), -127, 127), -128)
    (ps, pb) = s['p']
    q = dict(hs=sea(t['hs'], s['hs']), tp=sea(t['tp'], s['tp']), tl=sea(t['tl'], s['tl']), dl=deg(t['dl']), dp=deg(t['dp']),
             u=wind(t['u']), v=wind(t['v']),
             p=np.where(np.isfinite(t['p']), np.clip(np.round((np.nan_to_num(t['p']) - pb) * ps), 0, 65534), 65535))
    out = b''
    for k, typ in VARS:
        a = q[k].astype(np.int64)
        steps = a.shape[0]
        a = a.reshape(steps, -1).T                     # cells, then steps
        mod = 65536 if typ == 'u2' else 256
        d = np.diff(a, axis=1, prepend=0) % mod
        out += (d & 255).astype(np.uint8).tobytes() + ((d >> 8).astype(np.uint8).tobytes() if mod == 65536 else b'')
    return out


def tile_size(steps):
    return TILE * TILE * steps * sum(int(typ[1]) for _, typ in VARS)


def decode_tile(body, steps):
    """A tile's bytes (after gunzip) as {var: (steps, TILE, TILE)} in m, s,
    degrees, m/s and hPa, NaN where missing: encode_tile() undone."""
    a = np.frombuffer(body, dtype=np.uint8)
    if a.size != tile_size(steps):
        raise ValueError(f'a tile of {a.size} bytes; {steps} steps make {tile_size(steps)}')
    s, n, o, out = CELL_SCALE, TILE * TILE * steps, 0, {}
    for k, typ in VARS:
        if typ == 'u2':
            raw = a[o:o + n].astype(np.int64) + 256 * a[o + n:o + 2 * n].astype(np.int64)
            q = np.cumsum(raw.reshape(-1, steps), axis=1) % 65536
            o += 2 * n
        else:
            q = np.cumsum(a[o:o + n].astype(np.int64).reshape(-1, steps), axis=1) % 256
            if typ == 'i1':
                q = (q + 128) % 256 - 128
            o += n
        q = q.T.reshape(steps, TILE, TILE).astype(np.float64)
        if k in ('hs', 'tp', 'tl'):
            v = np.where(q == 255, np.nan, q / s[k])
        elif k in ('dl', 'dp'):
            v = np.where(q == 255, np.nan, q * s['dir'])
        elif k in ('u', 'v'):
            v = np.where(q == -128, np.nan, q / s['wind'])
        else:
            v = np.where(q == 65535, np.nan, q / s['p'][0] + s['p'][1])
        out[k] = v
    return out


def manifest_entry(dirname, names):
    """The manifest's cells: where the run's tiles are and how to read them."""
    return dict(lattice=LATTICE, tile=TILE, box=CELL_BOX, dir=dirname, file='{dir}/{tile}.bin.gz', tiles=names,
                vars=[k for k, _ in VARS], scale=CELL_SCALE, encoding=ENCODING)
