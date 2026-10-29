"""The sea bed as a layer for the chart: depth bands over the square.

depth.json holds, for each depth in DEPTHS, the sea at least that deep, as
rings in the square's km, quantised to 0.1 km and delta-encoded like the
base map's and the ice's (fill even-odd: a ring inside a ring is a hole).
The bands nest, so drawn shallowest first, each deeper one darker, they make
a shaded chart of the depths: the shallows of the southern North Sea and
Dogger Bank, the Norwegian Trench, the shelf edge off Scotland and Norway.

The depths are AWS's open Terrain Tiles (terrarium PNGs), whose sea bed is
NOAA's ETOPO1, about 1.8 km. Coarse beside EMODnet's 115 m, but the layer is
drawn at the scale of the whole square, where a band 2 km out is a pixel.
Sampled on a 2 km grid over the square and smoothed a little, so the bands
don't follow ETOPO1's pixels; bands under MIN_KM2 are dropped. The land is
drawn on top of it, so the coast is the base map's, not this.

It's a picture of the sea bed, not the depths the swell forecast should use:
for those (and anything near the coast), EMODnet.

With the charts job's requirements (requirements/charts.txt):

  python scripts/depth_layer.py assets/depth.json [preview.png]
"""
import io
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from grid import X0, X1, Y0, Y1, nodes

TILES = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'
SOURCE = 'NOAA ETOPO1, by AWS Terrain Tiles (terrarium)'
ZOOM = 6                       # ~1.2 km a pixel at 60°N: finer than ETOPO1
STEP_KM = 2
SMOOTH_KM = 3
DEPTHS = [20, 30, 40, 50, 70, 100, 200, 500, 1000, 2000, 3000]   # m
SIMPLIFY_KM = 0.5
MIN_KM2 = 8
MAX_LAT = 85.05                # web mercator's edge: no tiles north of it


def get(url, timeout=60):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def tile(x, y, z=ZOOM):
    """One tile's elevations (m, up is positive), 256 x 256."""
    from PIL import Image
    px = np.asarray(Image.open(io.BytesIO(get(TILES.format(z=z, x=x, y=y)))).convert('RGB'), dtype=np.float64)
    return px[..., 0] * 256 + px[..., 1] + px[..., 2] / 256 - 32768


def pixels(lon, lat, z=ZOOM):
    """Web mercator pixel coordinates at zoom z."""
    n = 256 * 2 ** z
    phi = np.radians(np.clip(lat, -MAX_LAT, MAX_LAT))
    return (lon + 180) / 360 * n, (1 - np.log(np.tan(phi) + 1 / np.cos(phi)) / np.pi) / 2 * n


def elevation(lon, lat, z=ZOOM):
    """Elevation (m) at each lon/lat, bilinear between the tiles' pixels; NaN
    north of the tiles."""
    n = 256 * 2 ** z
    px, py = pixels(lon, lat, z)
    px, py = px - 0.5, py - 0.5            # pixel centres
    x0, y0 = np.floor(px).astype(int), np.floor(py).astype(int)
    need = {((x // 256) % 2 ** z, y // 256) for xs, ys in ((x0, y0), (x0 + 1, y0 + 1))
            for x, y in zip(xs.ravel(), np.clip(ys, 0, n - 1).ravel())}
    with ThreadPoolExecutor(16) as ex:
        tiles = dict(zip(need, ex.map(lambda t: tile(*t, z), need)))
    print(f'{len(tiles)} tiles at zoom {z}')

    def at(x, y):
        x, y = x % n, np.clip(y, 0, n - 1)
        out = np.empty(x.shape)
        for (tx, ty), t in tiles.items():
            m = (x // 256 == tx) & (y // 256 == ty)
            out[m] = t[y[m] % 256, x[m] % 256]
        return out
    fx, fy = px - x0, py - y0
    e = (at(x0, y0) * (1 - fx) * (1 - fy) + at(x0 + 1, y0) * fx * (1 - fy) +
         at(x0, y0 + 1) * (1 - fx) * fy + at(x0 + 1, y0 + 1) * fx * fy)
    return np.where(lat > MAX_LAT, np.nan, e)


def bands(depth, levels=DEPTHS):
    """[(level, [ring, ...]), ...]: the sea at least each level deep, as rings
    in the square's km (x east, y north), exteriors and holes alike."""
    import contourpy
    import shapely
    from shapely.geometry import Polygon
    ny, nx = depth.shape
    xs, ys = np.linspace(X0, X1, nx), np.linspace(Y0, Y1, ny)
    gen = contourpy.contour_generator(xs, ys, np.nan_to_num(depth, nan=-1), fill_type='OuterOffset')
    out = []
    for lev in levels:
        rings = []
        for pts, offs in zip(*gen.filled(lev, 1e9)):
            parts = [pts[a:b] for a, b in zip(offs[:-1], offs[1:])]
            poly = shapely.make_valid(Polygon(parts[0], parts[1:])).simplify(SIMPLIFY_KM)
            for p in getattr(poly, 'geoms', [poly]):
                if p.geom_type != 'Polygon' or p.area < MIN_KM2:
                    continue
                rings.append(np.asarray(p.exterior.coords)[:-1])
                rings += [np.asarray(h.coords)[:-1] for h in p.interiors if shapely.Polygon(h).area >= MIN_KM2]
        out.append((lev, rings))
    return out


def enc(pts):
    q = np.round(np.asarray(pts) * 10).astype(int)
    return np.concatenate([q[:1], np.diff(q, axis=0)]).ravel().tolist()


def layer(path, preview=None):
    from scipy.ndimage import gaussian_filter
    n = int(round((X1 - X0) / STEP_KM)) + 1
    lon, lat = nodes(n)
    depth = -elevation(lon, lat)
    sea = np.isfinite(depth)
    depth = gaussian_filter(np.where(sea, depth, 0), SMOOTH_KM / STEP_KM)
    depth[~sea] = np.nan
    bs = bands(depth)
    out = dict(unit=0.1, source=SOURCE, bands=[dict(depth=lev, rings=[enc(r) for r in rings]) for lev, rings in bs])
    with open(path, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print(f'{path}: {sum(len(r) for _, r in bs)} rings, {sum(len(x) for _, r in bs for x in r)} points, '
          f'{os.path.getsize(path) / 1e3:.0f} kB')
    for lev, rings in bs:
        print(f'  {lev:>5} m  {len(rings):>4} rings')
    if preview:
        draw(path, preview)


def draw(path, png):
    """A look at the layer as the app would draw it: the bands shallowest
    first, the base map's land on top; the whole square and the North Sea."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch
    from grid import FWD
    here = os.path.dirname(os.path.abspath(__file__))
    with open(path) as f:
        d = json.load(f)
    with open(os.path.join(here, '..', 'assets', 'base.json')) as f:
        b = json.load(f)
    dec = lambda a, u: np.cumsum(np.asarray(a, dtype=float).reshape(-1, 2), axis=0) * u

    def patch(rings, **kw):
        verts, codes = [], []
        for r in rings:
            verts += [*r, r[0]]
            codes += [Path.MOVETO] + [Path.LINETO] * (len(r) - 1) + [Path.CLOSEPOLY]
        return PathPatch(Path(verts, codes), **kw)
    cmap = plt.get_cmap('Blues')
    fig, axes = plt.subplots(1, 2, figsize=(18, 9.4), gridspec_kw=dict(width_ratios=[1, 1]))
    sx, sy = FWD(np.array([-0.9724]), np.array([54.5838]))
    for ax, (xa, xb, ya, yb), title in ((axes[0], (X0, X1, Y1, Y0), 'The square'),
                                        (axes[1], (-700, 700, -4330, -2980), 'The North Sea')):
        ax.set_facecolor(cmap(0.12))
        for i, band in enumerate(d['bands']):
            rings = [dec(r, d['unit']) for r in band['rings']]
            if rings:
                ax.add_patch(patch(rings, facecolor=cmap(0.2 + 0.75 * i / (len(d['bands']) - 1)),
                                   edgecolor='white', linewidth=0.25, fill=True))
        ax.add_patch(patch([dec(r, b['unit']) for r in b['land']], facecolor='#e8e4da', edgecolor='#8a8577', linewidth=0.4))
        for g in b['grid']:
            p = dec(g, b['unit'])
            ax.plot(p[:, 0], p[:, 1], color='#00000022', linewidth=0.5)
        ax.plot(sx, sy, 'o', color='#d9480f', markersize=5)
        ax.annotate('Saltburn', (sx[0], sy[0]), xytext=(6, -12), textcoords='offset points', fontsize=9, color='#d9480f')
        ax.set_xlim(xa, xb); ax.set_ylim(ya, yb); ax.set_aspect('equal'); ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(title)
    handles = [plt.Rectangle((0, 0), 1, 1, color=cmap(0.12))] + \
              [plt.Rectangle((0, 0), 1, 1, color=cmap(0.2 + 0.75 * i / (len(d['bands']) - 1))) for i in range(len(d['bands']))]
    labels = [f'< {d["bands"][0]["depth"]} m'] + [f'{x["depth"]} m +' for x in d['bands']]
    fig.legend(handles, labels, loc='lower center', ncol=len(labels), frameon=False, fontsize=9)
    fig.suptitle(f'Depth layer: {d["source"]}', fontsize=11)
    fig.tight_layout(rect=(0, 0.05, 1, 0.97))
    fig.savefig(png, dpi=110)
    print(f'{png}')


if __name__ == '__main__':
    layer(*sys.argv[1:3])
