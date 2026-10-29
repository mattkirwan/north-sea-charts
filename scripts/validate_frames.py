"""Do the published frames say what NOAA's model says?

Reads a run's frames as a phone would (the manifest, then each frame; or with
--local, builds them with chart_frames.py instead), and compares them with
the same run's own GRIB files on NOAA's bucket, re-read here with its own
bilinear sampler and its own choice of swell period, so a mistake in
chart_frames.py (units, orientation, the wind's rotation, the swell period,
what smoothing and rounding do) shows up as a difference rather than as a
chart that looks right. At a set of points and over each whole grid:
pressure (hPa), wind speed (m/s) and direction, wave height (m) and period (s).

  python scripts/validate_frames.py [--steps 0,24,72] [--frames-url URL]
                                    [--local RUN] [--json OUT.json]
                                    [--wetterzentrale DIR]

Exits 1 when a difference is past its limit (LIMITS). The limits are for the
differences we expect: smoothing and rounding, not a wrong number.

Wetterzentrale is for looking at only. --wetterzentrale DIR saves, for each
step, our frame drawn beside Wetterzentrale's chart of the same run and hour,
for a person to compare by eye. Its charts are somebody else's work: they are
never read for numbers, never published, never uploaded by a workflow (this
repository is public), and DIR must be ignored by git (validation/ is) or
nothing is written. tests/test_validate.py holds the line.

Standard library, numpy, scipy and the frames job's requirements (matplotlib
too, for the pictures).
"""
import argparse
import datetime as dt
import gzip
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chart_frames as cf  # noqa: E402
import check_fresh  # noqa: E402
import gfs_latest  # noqa: E402

BRANCH = 'https://raw.githubusercontent.com/mattkirwan/north-sea-charts/frames/'
STEPS = [0, 24, 72, 120, 240, 384]
# Where to look: land and sea for the atmosphere, sea for the waves. Tees Bay is
# the wave model's cell nearest Saltburn (wave_model.py).
POINTS = [
    ('Tees Bay', 54.75, -1.0),
    ('Mid North Sea', 56.5, 2.5),
    ('Northern North Sea', 60.5, 1.5),
    ('Skagerrak', 58.0, 9.0),
    ('Norwegian Sea', 66.0, 3.0),
    ('West of the Hebrides', 57.0, -12.0),
    ('South of Iceland', 62.5, -20.0),
    ('Biscay', 46.5, -7.0),
]
# What we expect smoothing, 40 km sampling and rounding to leave, per point and
# over a whole grid (root mean square). Set from the first runs; a wrong unit,
# a flipped grid or a bad rotation is far outside them.
LIMITS = dict(p_point=2.0, p_rms=0.8, wind_point=2.5, wind_rms=0.8, dir_point=25.0,
              hs_point=0.35, hs_rms=0.12, tp_point=1.5, tp_rms=0.6)
MIN_WIND_FOR_DIRECTION = 5.0     # m/s: below it the direction is mostly noise
MIN_HS_FOR_PERIOD = 0.5          # m: a flat sea's period means little


# ---- Reading what we publish ----------------------------------------------------------

def decode(body, P, S):
    """A frame's bytes (after gunzip) as hPa, m/s along the square's axes, m and s
    (NaN where there's no sea): chart_frames.encode() undone."""
    n, m = P * P, S * S
    a = np.frombuffer(body, dtype=np.uint8)
    if a.size != 4 * n + 2 * m:
        raise ValueError(f'a frame of {a.size} bytes; the grids make {4 * n + 2 * m}')
    (ps, pb), sc = cf.SCALE['p'], cf.SCALE

    def rows(x, k, mod):
        return np.cumsum(x.reshape(k, k).astype(np.int64), axis=1) % mod
    p = rows(a[:n].astype(np.int64) + 256 * a[n:2 * n].astype(np.int64), P, 65536) / ps + pb
    signed = lambda q: ((q + 128) % 256 - 128) / sc['wind']
    ux, uy = signed(rows(a[2 * n:3 * n], P, 256)), signed(rows(a[3 * n:4 * n], P, 256))
    sea = lambda q, k: np.where(q == 255, np.nan, q / k)
    h = sea(rows(a[4 * n:4 * n + m], S, 256), sc['h'])
    t = sea(rows(a[4 * n + m:], S, 256), sc['t'])
    return dict(p=p, ux=ux, uy=uy, h=h, t=t)


def published(base, manifest, step):
    url = check_fresh.frame_url(base, manifest, step)
    return gzip.decompress(check_fresh.get(url))


def frame_at(fr, name, lon, lat):
    """A frame's grid, bilinear, at a point; NaN if any corner is."""
    n = fr[name].shape[0]
    x, y = cf.FWD(lon, lat)
    fx, fy = (x - cf.X0) / (cf.X1 - cf.X0) * (n - 1), (y - cf.Y0) / (cf.Y1 - cf.Y0) * (n - 1)
    if not (0 <= fx <= n - 1 and 0 <= fy <= n - 1):
        raise ValueError(f'{lat}N {lon}E is outside the square')
    return bilinear(fr[name], fy, fx)


def bilinear(grid, r, c):
    """grid at fractional row r and column c (arrays or scalars); NaN if any corner is."""
    r, c = np.asarray(r, dtype=float), np.asarray(c, dtype=float)
    r0 = np.clip(np.floor(r).astype(int), 0, grid.shape[0] - 2)
    c0 = np.clip(np.floor(c).astype(int), 0, grid.shape[1] - 2)
    fr, fc = r - r0, c - c0
    return ((1 - fr) * (1 - fc) * grid[r0, c0] + (1 - fr) * fc * grid[r0, c0 + 1] +
            fr * (1 - fc) * grid[r0 + 1, c0] + fr * fc * grid[r0 + 1, c0 + 1])


# ---- Reading NOAA's own files ------------------------------------------------------------

class Source:
    """One hour of the run straight from NOAA's GRIBs, on its 0.25° grid."""

    def __init__(self, run, step):
        a = cf.fetch(gfs_latest.grib_url(run, step), cf.GFS)
        w = cf.fetch(cf.wave_url(run, step), cf.WAVE)
        self.lat0, self.lon0 = a['p'][1], a['p'][2]
        self.p, self.u, self.v = a['p'][0] / 100, a['u'][0], a['v'][0]
        self.wlat0, self.wlon0 = w['hs'][1], w['hs'][2]
        self.hs = w['hs'][0]
        # The period we say: the longest of the separate swells of 0.1 m or more,
        # else the peak period. Worked out here from the model's own partitions.
        periods = [np.where(np.nan_to_num(w[f'sh{k}'][0]) >= cf.LONG_MIN_M, w[f'sp{k}'][0], -1) for k in (1, 2, 3)]
        longest = np.maximum.reduce(periods)
        self.tp = np.where(np.isfinite(self.hs), np.where(longest > 0, longest, w['tp'][0]), np.nan)

    def at(self, name, lon, lat):
        wave = name in ('hs', 'tp')
        lat0, lon0 = (self.wlat0, self.wlon0) if wave else (self.lat0, self.lon0)
        return bilinear(getattr(self, name), (lat0 - lat) / 0.25, (lon - lon0) / 0.25)


# ---- Comparing -----------------------------------------------------------------------------

def angle_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def compare(fr, src, grid_lon, grid_lat, slon, slat):
    """Differences (ours - NOAA's) at the points and over the grids, as a dict."""
    out = dict(points=[], grid={})
    for name, lat, lon in POINTS:
        lam = np.radians(lon)
        ux, uy = frame_at(fr, 'ux', lon, lat), frame_at(fr, 'uy', lon, lat)
        u, v = ux * np.cos(lam) + uy * np.sin(lam), -ux * np.sin(lam) + uy * np.cos(lam)
        su, sv = src.at('u', lon, lat), src.at('v', lon, lat)
        row = dict(point=name, lat=lat, lon=lon,
                   p=[round(float(frame_at(fr, 'p', lon, lat)), 2), round(float(src.at('p', lon, lat)), 2)],
                   wind=[round(float(np.hypot(u, v)), 2), round(float(np.hypot(su, sv)), 2)],
                   hs=[round(float(frame_at(fr, 'h', lon, lat)), 2), round(float(src.at('hs', lon, lat)), 2)],
                   tp=[round(float(frame_at(fr, 't', lon, lat)), 2), round(float(src.at('tp', lon, lat)), 2)])
        # to_/from direction doesn't matter: both are the way the wind blows.
        row['dir'] = [round(float(np.degrees(np.arctan2(u, v)) % 360), 1), round(float(np.degrees(np.arctan2(su, sv)) % 360), 1)]
        out['points'].append(row)
    # Whole grids: the frame's nodes, and NOAA's value at each.
    lam = np.radians(grid_lon)
    sp = np.hypot(fr['ux'], fr['uy'])
    ref_p = src.at('p', grid_lon, grid_lat)
    ref_wind = np.hypot(src.at('u', grid_lon, grid_lat), src.at('v', grid_lon, grid_lat))
    ref_h, ref_t = src.at('hs', slon, slat), src.at('tp', slon, slat)
    for key, ours, ref in (('p', fr['p'], ref_p), ('wind', sp, ref_wind), ('hs', fr['h'], ref_h), ('tp', fr['t'], ref_t)):
        d = (ours - ref)
        # Where either has no sea, or the model's cells are half land, there's nothing to compare.
        ok = np.isfinite(d)
        if key == 'tp':
            ok &= np.isfinite(ref_h) & (ref_h >= MIN_HS_FOR_PERIOD)
        d = d[ok]
        worst = np.unravel_index(np.nanargmax(np.where(ok, np.abs(ours - ref), -1)), ok.shape)
        lon_g, lat_g = (slon, slat) if key in ('hs', 'tp') else (grid_lon, grid_lat)
        out['grid'][key] = dict(worst_at=[round(float(lat_g[worst]), 1), round(float(lon_g[worst]), 1)], n=int(d.size), bias=round(float(d.mean()), 3), rms=round(float(np.sqrt((d ** 2).mean())), 3),
                                p99=round(float(np.percentile(np.abs(d), 99)), 3), max=round(float(np.abs(d).max()), 3))
    return out


def problems(res):
    """Sentences for every difference past its limit; empty if none."""
    out, L = [], LIMITS
    for r in res['points']:
        for key, lim, unit in (('p', L['p_point'], 'hPa'), ('wind', L['wind_point'], 'm/s'),
                               ('hs', L['hs_point'], 'm'), ('tp', L['tp_point'], 's')):
            ours, theirs = r[key]
            if key == 'tp' and not (r['hs'][1] >= MIN_HS_FOR_PERIOD):
                continue
            if np.isnan(theirs) and not np.isnan(ours):
                continue   # NOAA has no sea in a corner here; the frame fills it from the nearest sea (to_coast)
            if np.isnan(ours):
                out.append(f"{r['point']}: {key} is {ours} here and {theirs} in NOAA's file")
            elif not np.isnan(ours) and abs(ours - theirs) > lim:
                out.append(f"{r['point']}: {key} {ours} against NOAA's {theirs} {unit} (limit {lim})")
        if r['wind'][1] >= MIN_WIND_FOR_DIRECTION and angle_diff(*r['dir']) > L['dir_point']:
            out.append(f"{r['point']}: wind blowing towards {r['dir'][0]}° against NOAA's {r['dir'][1]}° (limit {L['dir_point']}°)")
    for key, lim, unit in (('p', L['p_rms'], 'hPa'), ('wind', L['wind_rms'], 'm/s'), ('hs', L['hs_rms'], 'm'), ('tp', L['tp_rms'], 's')):
        g = res['grid'][key]
        if g['n'] < 100:
            out.append(f'{key}: only {g["n"]} cells to compare')
        elif g['rms'] > lim:
            out.append(f"{key}: root mean square {g['rms']} {unit} over the grid (limit {lim}), worst {g['max']}")
    return out


# ---- Wetterzentrale: to look at, nothing more ---------------------------------------------------

def git_ignored(path):
    return subprocess.run(['git', 'check-ignore', '-q', path], cwd=os.path.join(HERE, '..'), capture_output=True).returncode == 0


def ours_image(fr, m, run, step):
    """Our frame as a picture, for placing beside another chart: pressure as
    colour and isobars every 4 hPa, the land from the app's base map, a graticule."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    P = fr['p'].shape[0]
    xs, ys = np.linspace(cf.X0, cf.X1, P), np.linspace(cf.Y0, cf.Y1, P)
    fig, ax = plt.subplots(figsize=(8, 8), dpi=80)
    ax.contourf(xs, ys, fr['p'], levels=np.arange(940, 1060, 4), cmap='RdBu_r', alpha=0.6, extend='both')
    c = ax.contour(xs, ys, fr['p'], levels=np.arange(940, 1060, 4), colors='k', linewidths=0.6)
    ax.clabel(c, fmt='%d', fontsize=6)
    with open(os.path.join(HERE, '..', 'assets', 'base.json')) as f:
        base = json.load(f)
    for ring in base['land']:
        a = np.cumsum(np.array(ring, dtype=float).reshape(-1, 2), axis=0) * base['unit']
        ax.plot(a[:, 0], a[:, 1], 'k-', lw=0.5)
    for lat in range(40, 90, 10):
        g = np.array([cf.FWD(lon, lat) for lon in np.linspace(-80, 80, 160)])
        ax.plot(g[:, 0], g[:, 1], color='grey', lw=0.3)
    for lon in range(-60, 61, 20):
        g = np.array([cf.FWD(lon, lat) for lat in np.linspace(35, 88, 60)])
        ax.plot(g[:, 0], g[:, 1], color='grey', lw=0.3)
    ax.set_xlim(cf.X0, cf.X1); ax.set_ylim(cf.Y1, cf.Y0); ax.set_aspect('equal'); ax.axis('off')
    ax.set_title(f'Ours (NOAA GFS) {run:%Y-%m-%d %Hz} +{step} h')
    fig.tight_layout()
    return fig


def side_by_side(fr, run, step, outdir):
    import io
    import matplotlib.pyplot as plt
    import urllib.request
    url = f'https://wetterzentrale.de/maps/GFSOPEU{run:%H}_{step}_1.png'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; north-sea-charts internal validation)'})
    with urllib.request.urlopen(req, timeout=60) as r:
        theirs = plt.imread(io.BytesIO(r.read()), format='png')
    ours = ours_image(fr, None, run, step)
    ours.canvas.draw()
    mine = np.asarray(ours.canvas.buffer_rgba())
    plt.close(ours)
    fig, axs = plt.subplots(1, 2, figsize=(16, 8), dpi=80)
    axs[0].imshow(mine); axs[1].imshow(theirs)
    axs[1].set_title(f'Wetterzentrale GFS {run:%H}z +{step} h (internal comparison only)')
    for a in axs:
        a.axis('off')
    fig.tight_layout()
    path = os.path.join(outdir, f'f{step:03d}.png')
    fig.savefig(path)
    plt.close(fig)
    return path


# ---- Main ------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--steps', default=','.join(map(str, STEPS)))
    ap.add_argument('--frames-url', default=BRANCH, help='where the manifest is (default: the frames branch)')
    ap.add_argument('--no-r2', action='store_true', help="take frames from the branch, not the R2 address the manifest names")
    ap.add_argument('--local', metavar='RUN', help='build the frames here for RUN (2026-10-29-00z) instead of reading the published ones')
    ap.add_argument('--json', help='write the numbers here')
    ap.add_argument('--wetterzentrale', metavar='DIR', help='also save side-by-side pictures here, to look at (never published)')
    args = ap.parse_args(argv)
    steps = [int(s) for s in args.steps.split(',')]

    if args.wetterzentrale:
        outdir = os.path.abspath(args.wetterzentrale)
        os.makedirs(outdir, exist_ok=True)
        if not git_ignored(os.path.join(outdir, 'x.png')):
            raise SystemExit(f'{outdir} is not ignored by git; Wetterzentrale pictures are never committed. Use validation/.')
    if args.local:
        run = dt.datetime.strptime(args.local, '%Y-%m-%d-%Hz')
        P, S = cf.P_N, cf.S_N
        manifest = None
    else:
        manifest = json.loads(check_fresh.get(f'{args.frames_url}manifest.json?t={int(dt.datetime.now().timestamp())}'))
        run = dt.datetime.fromtimestamp(manifest['run'] / 1000, dt.timezone.utc).replace(tzinfo=None)
        P, S = manifest['grids']['p'], manifest['grids']['s']
        if args.no_r2:
            manifest.pop('base', None)
        missing = [s for s in steps if s not in manifest['steps']]
        if missing:
            raise SystemExit(f'Not in the manifest: {missing}')
    print(f'Run {run:%Y-%m-%d %H}z, frames from {"a local build" if args.local else args.frames_url}')
    glon, glat = cf.nodes(P)
    slon, slat = cf.nodes(S)
    found, report = [], []
    for step in steps:
        body = cf.frame(run, step)[0] if args.local else published(args.frames_url, manifest, step)
        fr = decode(body, P, S)
        res = compare(fr, Source(run, step), glon, glat, slon, slat)
        res['step'] = step
        bad = problems(res)
        report.append(res)
        found += [f'+{step} h: {b}' for b in bad]
        g = res['grid']
        print(f"+{step:3d} h  p rms {g['p']['rms']:.2f} max {g['p']['max']:.2f} hPa (at {g['p']['worst_at'][0]}N {g['p']['worst_at'][1]}E) | wind rms {g['wind']['rms']:.2f} max {g['wind']['max']:.2f} m/s | "
              f"Hs rms {g['hs']['rms']:.2f} max {g['hs']['max']:.2f} m | Tp rms {g['tp']['rms']:.2f} max {g['tp']['max']:.2f} s" +
              (f'  <- {len(bad)} over' if bad else ''))
        if args.wetterzentrale:
            try:
                print('   saved', side_by_side(fr, run, step, outdir))
            except Exception as e:
                print(f'   no Wetterzentrale picture for +{step} h: {e}')
    if report:
        print('\nAt the points (ours / NOAA\'s), +%d h:' % report[0]['step'])
        for r in report[0]['points']:
            print(f"  {r['point']:22s} p {r['p'][0]:7.1f} / {r['p'][1]:7.1f}   wind {r['wind'][0]:5.1f} / {r['wind'][1]:5.1f}   "
                  f"Hs {r['hs'][0]:5.2f} / {r['hs'][1]:5.2f}   Tp {r['tp'][0]:5.1f} / {r['tp'][1]:5.1f}")
    if args.json:
        with open(args.json, 'w') as f:
            json.dump(dict(run=f'{run:%Y-%m-%d-%Hz}', limits=LIMITS, steps=report, problems=found), f, indent=1)
    for line in found:
        print('PROBLEM', line)
    print('Frames match NOAA\'s files within the limits' if not found else f'{len(found)} differences past the limits')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
