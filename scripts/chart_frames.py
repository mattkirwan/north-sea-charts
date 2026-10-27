"""The chart app's frames: NOAA's GFS and GFS-Wave on our own square of sea.

The app draws the chart itself (isobars, wind arrows, swell bands), so all it
needs is the model's fields on a regular grid over the square, frame by frame.
The square is polar stereographic on the Greenwich meridian, about 4,600 km a
side, from Cape Farewell and northern Svalbard down to Biscay and across to
Gdansk and North Cape. Every frame of a run is written: hourly to +120 h, then
3-hourly to +384 h, 209 in all, in a folder named for the run
(2026-10-26-06z/f000.bin.gz; the manifest's dir). A frame's address names its
run, so the app (and the phone's kept copies) can never take one run's frame
for another's: once the next run replaces the branch, the old addresses are
gone rather than quietly serving the new run's frames.

Each frame is one gzipped file in this order:
  pressure   uint16  (hPa - 850) * 20, smoothed        P x P   low bytes, then high bytes
  wind east  int8    m/s * 2, along the square's x     P x P
  wind north int8    m/s * 2, along the square's y     P x P   (y up)
  height     uint8   significant wave height, m * 10   S x S   (255 = no sea)
  period     uint8   period of the longest swell, s*10 S x S   (255 = no sea)
Rows run north to south (top of the square first), columns west to east, and
each grid's nodes sit on the square's edges. Every row is stored as the
differences along it (modulo 256, or 65536 for pressure), which gzip packs
much tighter: a frame is about 50 kB. The period is the longest of the
model's separate swells of 0.1 m or more, or the peak period where there's
only wind sea: the same as the old charts.

  python scripts/chart_frames.py OUT_DIR [RUN as 2026-10-26-06z] [--steps 0,1,2]
  python scripts/chart_frames.py --base assets/base.json     # the land, once
"""
import datetime as dt
import gzip
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import gfs_latest

PROJ4 = '+proj=stere +lat_0=90 +lat_ts=60 +lon_0=0 +R=6371229 +units=km'
X0, X1, Y0, Y1 = -2805.0, 1795.0, -650.0, -5250.0   # km: west, east, north, south
P_N = 116                                          # pressure and wind: ~40 km
S_N = 185                                          # swell: 25 km, the model's grid
AREA = dict(w=-80, e=72, s=35, n=88)               # what to cut from the global grids
STEPS = list(range(0, 121)) + list(range(123, 385, 3))
GFS = {'PRMSL:mean sea level': 'p', 'UGRD:10 m above ground': 'u', 'VGRD:10 m above ground': 'v'}
WAVE = {'HTSGW:surface': 'hs', 'PERPW:surface': 'tp', **{f'SWELL:{k} in sequence': f'sh{k}' for k in (1, 2, 3)},
        **{f'SWPER:{k} in sequence': f'sp{k}' for k in (1, 2, 3)}}
LONG_MIN_M = 0.1
R = 6371.229
WAIT_MIN = 90


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
    """The grid's nodes: x west to east, y north to south (km), and their lon/lat."""
    xs, ys = np.linspace(X0, X1, n), np.linspace(Y0, Y1, n)
    gx, gy = np.meshgrid(xs, ys)
    lon, lat = INV(gx, gy)
    return lon, lat


def get(url, rng=None, timeout=90):
    import urllib.request
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'Range': f'bytes={rng[0]}-{rng[1]}'} if rng else {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def get_idx(url):
    import urllib.error
    end = time.time() + WAIT_MIN * 60
    while True:
        try:
            return get(url + '.idx').decode().splitlines()
        except urllib.error.HTTPError as e:
            if e.code not in (403, 404) or time.time() > end:
                raise
            time.sleep(60)


def fetch(url, wanted):
    """Just the wanted fields of one GRIB file, as (values, lat0, lon0) on the
    0.25° grid cut to AREA (lat from north, lon from west)."""
    import xarray as xr
    idx = get_idx(url)
    out = {}
    for i, line in enumerate(idx):
        parts = line.split(':')
        name = f'{parts[3]}:{parts[4]}'
        if name in wanted and wanted[name] not in out:
            start = int(parts[1])
            end = int(idx[i + 1].split(':')[1]) - 1 if i + 1 < len(idx) else ''
            with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as f:
                f.write(get(url, (start, end)))
            ds = xr.open_dataset(f.name, engine='cfgrib', backend_kwargs={'indexpath': ''})
            var = ds[list(ds.data_vars)[0]]
            var = var.assign_coords(longitude=((var.longitude + 180) % 360) - 180).sortby('longitude')
            if var.latitude[0] < var.latitude[-1]:
                var = var.sortby('latitude', ascending=False)
            var = var.sel(latitude=slice(AREA['n'], AREA['s']), longitude=slice(AREA['w'], AREA['e'])).load()
            out[wanted[name]] = (var.values.astype(np.float64), float(var.latitude[0]), float(var.longitude[0]))
            os.unlink(f.name)
    missing = set(wanted.values()) - set(out)
    if missing:
        raise RuntimeError(f'{url}: missing {sorted(missing)}')
    return out


def sample(field, lat0, lon0, lon, lat, step=0.25):
    """Bilinear samples of a 0.25° field at lon/lat; NaN where any corner is NaN."""
    from scipy.ndimage import map_coordinates
    r = (lat0 - lat) / step
    c = (lon - lon0) / step
    ok = np.isfinite(field)
    val = map_coordinates(np.where(ok, field, 0.0), [r, c], order=1, mode='nearest')
    w = map_coordinates(ok.astype(np.float64), [r, c], order=1, mode='nearest')
    return np.where(w > 0.999, val, np.where(w > 0.5, val / np.maximum(w, 1e-9), np.nan))


def to_coast(field, cells=2):
    """Fill the model's missing cells along the coast with the nearest sea value,
    up to `cells` away, so the bands reach under the land drawn on top."""
    from scipy.ndimage import distance_transform_edt
    bad = ~np.isfinite(field)
    if not bad.any():
        return field
    d, (i, j) = distance_transform_edt(bad, return_indices=True)
    out = field[i, j]
    out[d > cells] = np.nan
    return out


def frame(run, step):
    """One frame's bytes (before gzip) and a few numbers to check it by."""
    from scipy.ndimage import gaussian_filter
    a = fetch(gfs_latest.grib_url(run, step), GFS)
    w = fetch(wave_url(run, step), WAVE)
    plon, plat = nodes(P_N)
    slon, slat = nodes(S_N)
    p = sample(a['p'][0] / 100, a['p'][1], a['p'][2], plon, plat)
    p = gaussian_filter(p, 0.9, mode='nearest')
    if not np.isfinite(p).all() or p.min() < 870 or p.max() > 1095:
        raise RuntimeError(f'f{step:03d}: implausible pressure {np.nanmin(p):.0f}-{np.nanmax(p):.0f}')
    u = sample(a['u'][0], a['u'][1], a['u'][2], plon, plat)
    v = sample(a['v'][0], a['v'][1], a['v'][2], plon, plat)
    if not (np.isfinite(u).all() and np.isfinite(v).all()) or np.hypot(u, v).max() > 90:
        raise RuntimeError(f'f{step:03d}: implausible wind')
    lam = np.radians(plon)
    ux, uy = u * np.cos(lam) - v * np.sin(lam), u * np.sin(lam) + v * np.cos(lam)
    hs, lat0, lon0 = w['hs']
    per = np.stack([np.where(np.nan_to_num(w[f'sh{k}'][0]) >= LONG_MIN_M, w[f'sp{k}'][0], np.nan) for k in (1, 2, 3)])
    tp = np.where(np.isfinite(hs), np.nan_to_num(np.nanmax(np.where(np.isfinite(per), per, -1), axis=0), nan=-1), np.nan)
    tp = np.where(tp > 0, tp, w['tp'][0])
    h = sample(to_coast(hs), lat0, lon0, slon, slat)
    t = sample(to_coast(tp), lat0, lon0, slon, slat)
    # About 70% of the square is sea; much less means the wave model's file is
    # broken (all NaN would pass the checks below unseen), not sea ice.
    if np.isfinite(h).mean() < 0.4 or np.isfinite(t).mean() < 0.4:
        raise RuntimeError(f'f{step:03d}: waves over only {np.isfinite(h).mean():.0%} of the square')
    if np.nanmax(h) > 25 or np.nanmax(t) > 35:
        raise RuntimeError(f'f{step:03d}: implausible waves {np.nanmax(h):.1f} m {np.nanmax(t):.0f} s')
    q = lambda x, k: np.where(np.isfinite(x), np.clip(np.round(x * k), 0, 254), 255).astype(np.int64)
    rows = lambda a, m: (np.diff(a, axis=1, prepend=0) % m)
    pd = rows(np.round((p - 850) * 20).astype(np.int64), 65536)
    body = ((pd & 255).astype(np.uint8).tobytes() + (pd >> 8).astype(np.uint8).tobytes() +
            rows(np.clip(np.round(ux * 2), -127, 127).astype(np.int64), 256).astype(np.uint8).tobytes() +
            rows(np.clip(np.round(uy * 2), -127, 127).astype(np.int64), 256).astype(np.uint8).tobytes() +
            rows(q(h, 10), 256).astype(np.uint8).tobytes() + rows(q(t, 10), 256).astype(np.uint8).tobytes())
    return body, dict(p=[round(float(p.min()), 1), round(float(p.max()), 1)], h=round(float(np.nanmax(h)), 1),
                      t=round(float(np.nanmax(t)), 1), wind=round(float(np.nanmax(np.hypot(u, v))), 1))


def wave_url(run, step):
    return f'{gfs_latest.BUCKET}/gfs.{run:%Y%m%d}/{run:%H}/wave/gridded/gfswave.t{run:%H}z.global.0p25.f{step:03d}.grib2'


def _one(args):
    run, step, out = args
    for attempt in range(3):
        try:
            body, stats = frame(run, step)
            with open(os.path.join(out, f'f{step:03d}.bin.gz'), 'wb') as f:
                f.write(gzip.compress(body, 9))
            return step, stats, None
        except Exception as e:
            err = f'{type(e).__name__}: {e}'
            time.sleep(20)
    return step, None, err


def run_dir(run):
    return f'{run:%Y-%m-%d-%H}z'


def run_frames(out, run, steps):
    d = run_dir(run)
    os.makedirs(os.path.join(out, d), exist_ok=True)
    t0 = time.time()
    done, failed = {}, {}
    with ProcessPoolExecutor(max_workers=int(os.environ.get('WORKERS', '6'))) as pool:
        for step, stats, err in pool.map(_one, [(run, s, os.path.join(out, d)) for s in steps]):
            if err:
                failed[step] = err
                print(f'  f{step:03d} FAILED {err}', flush=True)
            else:
                done[step] = stats
                print(f'  f{step:03d} {stats}', flush=True)
    print(f'{len(done)} frames in {time.time() - t0:.0f} s; failed: {sorted(failed)}')
    good = sorted(done)
    # Publish only an unbroken run of frames from the start.
    upto = next((i for i, s in enumerate(steps) if s not in done), len(steps))
    if upto < len(steps) * 0.6:
        raise SystemExit(f'Only {upto} frames in a row; not publishing')
    keep = steps[:upto]
    for s in good:
        if s not in keep:
            os.unlink(os.path.join(out, d, f'f{s:03d}.bin.gz'))
    manifest = dict(
        run=int(run.replace(tzinfo=dt.timezone.utc).timestamp() * 1000), runLabel=gfs_latest.label(run),
        made=int(time.time() * 1000), steps=keep, dir=d, file='{dir}/f{step}.bin.gz', pad=3,
        square=dict(x0=X0, x1=X1, y0=Y0, y1=Y1, proj=PROJ4),
        grids=dict(p=P_N, s=S_N), scale=dict(p=[20, 850], wind=2, h=10, t=10), encoding='row-delta-v1',
        source='NOAA GFS 0.25° (pressure, 10 m wind) and GFS-Wave 0.25° (height, longest swell period)')
    with open(os.path.join(out, 'manifest.json'), 'w') as f:
        json.dump(manifest, f, separators=(',', ':'))
    size = sum(os.path.getsize(os.path.join(out, d, f'f{s:03d}.bin.gz')) for s in keep)
    print(f'manifest: {len(keep)} frames, {size / 1e6:.1f} MB, {size / len(keep) / 1e3:.0f} kB a frame')


def base(path):
    """The land (Natural Earth 10 m) and a 10° graticule in the square's km,
    quantised to 0.1 km and delta-encoded, for the app to draw once. Cut well
    beyond the square, so the edges never show."""
    import cartopy.io.shapereader as shpreader
    import shapely
    from shapely.geometry import box, LineString
    from shapely.ops import transform
    mx, my = 0.35 * (X1 - X0), 0.45 * (Y0 - Y1)
    clip = box(X0 - mx, Y1 - my, X1 + mx, Y0 + my)
    lonlat_clip = box(-110, 25, 110, 90)
    proj = lambda x, y, z=None: FWD(np.asarray(x), np.asarray(y))
    rings = []
    for geom in shpreader.Reader(shpreader.natural_earth('10m', 'physical', 'land')).geometries():
        g = geom.intersection(lonlat_clip)
        if g.is_empty:
            continue
        g = transform(proj, shapely.segmentize(g, 0.05)).buffer(0).intersection(clip).simplify(0.3)
        polys = [g] if g.geom_type == 'Polygon' else [p for p in getattr(g, 'geoms', []) if p.geom_type == 'Polygon']
        for poly in polys:
            if poly.area < 2:
                continue
            for r in [poly.exterior, *poly.interiors]:
                rings.append(np.asarray(r.coords)[:-1])
    enc = lambda pts: (lambda q: np.concatenate([q[:1], np.diff(q, axis=0)]).ravel().tolist())(np.round(np.asarray(pts) * 10).astype(int))
    grat = []
    for lat in range(40, 90, 10):
        lon = np.arange(-120, 120.1, 0.5)
        grat.append(np.column_stack(FWD(lon, np.full_like(lon, lat))))
    for lon in range(-120, 121, 10):
        lat = np.arange(30, 90.01, 0.5)
        grat.append(np.column_stack(FWD(np.full_like(lat, lon), lat)))
    grat = [g for g in (np.asarray(LineString(g).intersection(clip).coords) if not LineString(g).intersection(clip).is_empty
                        and LineString(g).intersection(clip).geom_type == 'LineString' else None for g in grat) if g is not None]
    out = dict(unit=0.1, square=dict(x0=X0, x1=X1, y0=Y0, y1=Y1), land=[enc(r) for r in rings], grid=[enc(g) for g in grat])
    with open(path, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print(f'{path}: {len(rings)} rings, {sum(len(r) for r in rings)} points, {os.path.getsize(path) / 1e3:.0f} kB')


if __name__ == '__main__':
    args = sys.argv[1:]
    if args[0] == '--base':
        base(args[1])
        raise SystemExit
    out = args[0]
    run = dt.datetime.strptime(args[1], '%Y-%m-%d-%Hz') if len(args) > 1 and not args[1].startswith('--') else gfs_latest.latest_run(full=True)
    steps = STEPS
    if '--steps' in args:
        steps = [int(s) for s in args[args.index('--steps') + 1].split(',')]
    print(f'Run {gfs_latest.label(run)}: {len(steps)} frames to +{steps[-1]} h')
    run_frames(out, run, steps)
