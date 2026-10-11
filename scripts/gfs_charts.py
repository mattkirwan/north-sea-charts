"""Draw our own North Sea pressure charts from NOAA's GFS model.

For the newest complete GFS run, downloads sea-level pressure and 500 hPa
geopotential height for each forecast hour (0-168, every 6 h) from NOAA's open
data on AWS, using the .idx files to fetch just those two fields, and draws a
chart per hour: isobars every 4 hPa with H/L centres, the 500 hPa height as
colour, coastlines. Writes PNGs and manifest.json into the output folder.

We don't forecast anything here: these are NOAA's numbers, drawn. Checks
before publishing: every frame present, pressures within physical limits.

  python scripts/gfs_charts.py OUT_DIR [--check]

--check also writes check/ images placing our chart beside Wetterzentrale's
for the same run and hour, and prints our pressure at Saltburn beside
Open-Meteo's GFS value, so the drawing can be verified.
"""
import datetime as dt
import io
import json
import os
import sys
import tempfile
import urllib.request

import matplotlib
matplotlib.use('Agg')
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.colors import LinearSegmentedColormap
from scipy.ndimage import gaussian_filter, maximum_filter, minimum_filter

BUCKET = 'https://noaa-gfs-bdp-pds.s3.amazonaws.com'
STEPS = list(range(0, 169, 6))
AREA = dict(w=-90, e=90, s=20, n=90)          # data we keep: well beyond the map, so colour fills it
VIEW = [-20, 20, 49, 78]                       # map extent: lon W, lon E, lat S, lat N
SALTBURN = (54.583, -0.973)
PROJ = ccrs.LambertConformal(central_longitude=5, central_latitude=62, standard_parallels=(55, 70))
FIELDS = {'PRMSL:mean sea level': 'prmsl', 'HGT:500 mb': 'gh'}

INK, PAPER, COAST = '#173242', '#E8EEF1', '#0F2230'
# 500 hPa height in decametres: cold (low) blues through a pale middle around
# 552 dam to warm (high) oranges; opaque, so bands don't show seams.
HGT_CMAP = LinearSegmentedColormap.from_list('h500', ['#2a1f7a', '#2443a8', '#2f7fd0', '#56b3d9', '#9fd6c9', '#e8e2a6', '#f2b65e', '#e5793a', '#c2452a', '#8f2420'])
HGT_LEVELS = np.arange(496, 605, 4)


def get(url, rng=None, timeout=60):
    req = urllib.request.Request(url, headers={'Range': f'bytes={rng[0]}-{rng[1]}'} if rng else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def exists(url):
    try:
        urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=30)
        return True
    except Exception:
        return False


def grib_url(run, step):
    return f'{BUCKET}/gfs.{run:%Y%m%d}/{run:%H}/atmos/gfs.t{run:%H}z.pgrb2.0p25.f{step:03d}'


def latest_run():
    """Newest run whose last frame is on the bucket (runs finish ~4-5 h after their start)."""
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    run = now.replace(hour=now.hour // 6 * 6)
    for _ in range(8):
        if exists(grib_url(run, STEPS[-1]) + '.idx'):
            return run
        run -= dt.timedelta(hours=6)
    raise SystemExit('No complete GFS run found in the last two days')


def fetch_fields(run, step):
    """Download just our two fields for one forecast hour and decode them."""
    url = grib_url(run, step)
    idx = get(url + '.idx').decode().splitlines()
    out = {}
    for i, line in enumerate(idx):
        parts = line.split(':')
        name = f'{parts[3]}:{parts[4]}'
        if name in FIELDS:
            start = int(parts[1])
            end = int(idx[i + 1].split(':')[1]) - 1 if i + 1 < len(idx) else ''
            data = get(url, (start, end))
            with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as f:
                f.write(data)
            ds = xr.open_dataset(f.name, engine='cfgrib', backend_kwargs={'indexpath': ''})
            var = ds[list(ds.data_vars)[0]]
            var = var.assign_coords(longitude=((var.longitude + 180) % 360) - 180).sortby('longitude')
            var = var.sel(latitude=slice(AREA['n'], AREA['s']), longitude=slice(AREA['w'], AREA['e'])).load()
            out[FIELDS[name]] = var
            os.unlink(f.name)
    if set(out) != set(FIELDS.values()):
        raise RuntimeError(f'f{step:03d}: missing fields, found {list(out)}')
    return out


def extrema(field, lons, lats, size, kind):
    """Local highs or lows in a smoothed field, away from the edges."""
    sm = gaussian_filter(field, 3)
    filt = maximum_filter if kind == 'H' else minimum_filter
    peaks = np.argwhere(sm == filt(sm, size=size, mode='nearest'))
    wide = filt(sm, size=size * 2, mode='nearest')  # keep only centres that dominate a wider area
    out = []
    for y, x in peaks:
        if 8 < y < field.shape[0] - 8 and 8 < x < field.shape[1] - 8 and abs(sm[y, x] - wide[y, x]) < 0.6:
            lo, la = float(lons[x]), float(lats[y])
            if VIEW[0] + 1.5 <= lo <= VIEW[1] - 1.5 and VIEW[2] + 1 <= la <= VIEW[3] - 1:  # whole label inside the map
                out.append((lo, la, float(field[y, x])))
    return out


def draw(run, step, f, path):
    p = f['prmsl'].values / 100.0                  # Pa -> hPa
    h = f['gh'].values / 10.0                      # gpm -> dam
    lons, lats = f['prmsl'].longitude.values, f['prmsl'].latitude.values
    # Size the image to the map's own shape so there are no empty margins.
    probe = plt.figure()
    pax = probe.add_axes([0, 0, 1, 1], projection=PROJ)
    pax.set_extent(VIEW, crs=ccrs.PlateCarree())
    x0, x1, y0, y1 = pax.get_extent()
    plt.close(probe)
    width = 9.0
    fig = plt.figure(figsize=(width, width * (y1 - y0) / (x1 - x0)), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1], projection=PROJ)
    ax.set_extent(VIEW, crs=ccrs.PlateCarree())
    ax.set_facecolor(INK)
    cf = ax.contourf(lons, lats, gaussian_filter(h, 1.0), levels=HGT_LEVELS, cmap=HGT_CMAP, extend='both', transform=ccrs.PlateCarree(), zorder=2, antialiased=False)
    cf.set_edgecolor('face')  # fill the hairline seams between bands
    ax.add_feature(cfeature.COASTLINE.with_scale('50m'), edgecolor=COAST, linewidth=0.9, zorder=3)
    ax.add_feature(cfeature.BORDERS.with_scale('50m'), edgecolor=COAST, linewidth=0.4, alpha=0.5, zorder=3)
    ps = gaussian_filter(p, 1.0)
    # Dark isobars read on every colour; a faint light halo keeps them clear on the darkest blues.
    halo = [pe.withStroke(linewidth=2.6, foreground=(1, 1, 1, 0.35))]
    cs = ax.contour(lons, lats, ps, levels=np.arange(920, 1072, 4), colors='#13202b', linewidths=1.1, transform=ccrs.PlateCarree(), zorder=4)
    cs.set_path_effects(halo)
    for t in ax.clabel(cs, fmt='%d', fontsize=10, inline=True, inline_spacing=5, colors='#13202b'):
        t.set_path_effects([pe.withStroke(linewidth=2.5, foreground='white')])
    white = [pe.withStroke(linewidth=3, foreground='white')]
    for kind, colour in (('L', '#c1121f'), ('H', '#0b3d91')):
        for lo, la, v in extrema(p, lons, lats, 48, kind):
            ax.text(lo, la, kind, color=colour, fontsize=24, fontweight='bold', ha='center', va='center', transform=ccrs.PlateCarree(), zorder=5, path_effects=white)
            ax.text(lo, la - 0.9, f'{v:.0f}', color=colour, fontsize=11, fontweight='bold', ha='center', va='top', transform=ccrs.PlateCarree(), zorder=5, path_effects=white)
    ax.plot(SALTBURN[1], SALTBURN[0], 'o', ms=6, color='#FFC23D', mec=COAST, mew=1, transform=ccrs.PlateCarree(), zorder=6)
    valid = run + dt.timedelta(hours=step)
    ax.text(0.012, 0.008, f'GFS {run:%Hz %d %b} +{step}h · valid {valid:%a %d %b %H}z · NOAA data', transform=ax.transAxes,
            color=COAST, fontsize=9, zorder=6)
    ax.axis('off')
    fig.savefig(path, facecolor=INK)
    plt.close(fig)
    return p, lons, lats


def sanity(step, p):
    lo, hi = float(np.nanmin(p)), float(np.nanmax(p))
    if np.isnan(p).any() or lo < 930 or hi > 1070:
        raise RuntimeError(f'f{step:03d}: implausible pressures {lo:.0f}-{hi:.0f} hPa')
    return lo, hi


def check(run, step, p, lons, lats, ours, outdir):
    """Side-by-side with Wetterzentrale's chart for the same run and hour, plus spot values."""
    os.makedirs(os.path.join(outdir, 'check'), exist_ok=True)
    yi, xi = np.abs(lats - SALTBURN[0]).argmin(), np.abs(lons - SALTBURN[1]).argmin()
    valid = run + dt.timedelta(hours=step)
    line = f'f{step:03d} valid {valid:%Y-%m-%d %H}z: our MSLP at Saltburn {p[yi, xi]:.1f} hPa'
    try:
        om = json.loads(get('https://api.open-meteo.com/v1/gfs?latitude=54.583&longitude=-0.973&hourly=pressure_msl'
                            f'&models=gfs_seamless&timezone=GMT&start_hour={valid:%Y-%m-%dT%H:00}&end_hour={valid:%Y-%m-%dT%H:00}'))
        line += f' | Open-Meteo GFS {om["hourly"]["pressure_msl"][0]} hPa'
    except Exception as e:
        line += f' | Open-Meteo unavailable ({e})'
    lo = np.unravel_index(np.argmin(p), p.shape)
    line += f' | deepest low {p[lo]:.0f} hPa at {lats[lo[0]]:.1f}N {lons[lo[1]]:.1f}E'
    print(line)
    try:
        wz = plt.imread(io.BytesIO(get(f'https://wetterzentrale.de/maps/GFSOPEU{run:%H}_{step}_1.png')), format='png')
        mine = plt.imread(ours)
        fig, axs = plt.subplots(1, 2, figsize=(16, 9.5), dpi=80)
        axs[0].imshow(mine); axs[0].set_title('Ours (NOAA GFS)')
        axs[1].imshow(wz); axs[1].set_title(f'Wetterzentrale GFS {run:%H}z +{step}h')
        for a in axs:
            a.axis('off')
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, 'check', f'f{step:03d}.png'))
        plt.close(fig)
    except Exception as e:
        print(f'  no Wetterzentrale image for comparison: {e}')


def main():
    outdir = sys.argv[1]
    do_check = '--check' in sys.argv
    os.makedirs(outdir, exist_ok=True)
    steps = [0, 24, 72] if os.environ.get('QUICK') else STEPS  # QUICK: a preview of the look
    run = latest_run()
    print(f'GFS run {run:%Y-%m-%d %H}z')
    # The workflow passes the run already published; nothing to do if it's this one.
    if os.environ.get('PUBLISHED_RUN') == f'{run:%Y-%m-%d %H}z' and not do_check and not os.environ.get('FORCE'):
        print('Already published; nothing to do.')
        return
    lows, highs = [], []
    for step in steps:
        f = fetch_fields(run, step)
        path = os.path.join(outdir, f'f{step:03d}.png')
        p, lons, lats = draw(run, step, f, path)
        lo, hi = sanity(step, p)
        lows.append(lo); highs.append(hi)
        print(f'  f{step:03d}: {lo:.0f}-{hi:.0f} hPa, {os.path.getsize(path) // 1024} KB')
        if do_check and step in (0, 24, 72, 120):
            check(run, step, p, lons, lats, path, outdir)
    manifest = dict(run=int(run.timestamp() * 1000), runLabel=f'{run:%Y-%m-%d %H}z', steps=steps, file='f%03d.png',
                    generated=int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000), source='NOAA GFS 0.25°',
                    pressure=dict(min=round(min(lows)), max=round(max(highs))))
    with open(os.path.join(outdir, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh)
    print(f'Wrote {len(steps)} charts and manifest.json')


if __name__ == '__main__':
    main()
