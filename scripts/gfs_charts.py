"""Draw our own North Sea pressure charts from NOAA's GFS model.

For the newest complete GFS run, downloads sea-level pressure and 500 hPa
geopotential height for every forecast hour the model gives (hourly to +120 h,
then every 3 hours to +384 h; see DRAW_STEPS) from NOAA's open
data on AWS, using the .idx files to fetch just those two fields, and draws a
chart per hour of the North Sea and Saltburn's swell window, portrait, for a
phone (see PROJ and EXTENT): sea-level pressure as bright colour (blues and purples for
lows, oranges and reds for highs) with isobars every 4 hPa, H/L centres and
coastlines. (500 hPa height is downloaded for the checks but not drawn.) Writes PNGs and manifest.json into the output folder,
plus ice.png, a transparent sea-ice layer from the latest ice chart (see draw_ice), with ice.zip, the chart itself;
plus fields.npz: the run's numbers themselves for the charted area, so we
keep the data as well as the pictures (see save_fields);
plus the wave layer: NOAA's wave model (GFS-Wave) for the same run and hours,
as two frames per hour on the same map: wave height (h000.png...) and the
period of the longest swell present (t000.png...) (see draw_waves). The app shows them in place of the
pressure charts.

The charts are NOAA's numbers, drawn. From the same numbers (see
swell_sources.py) come the swell window (window.json), bomb low alerts (in
the manifest) and our own swell forecast for Saltburn (forecast.json). Checks
before publishing: every frame present, pressures within physical limits.

  python scripts/gfs_charts.py OUT_DIR [--check]   # the first week (to FIRST)
  python scripts/gfs_charts.py OUT_DIR --rest      # then the rest of the run, added

--check also writes check/ images placing our chart beside Wetterzentrale's
for the same run and hour, and prints our pressure at Saltburn beside
Open-Meteo's GFS value, so the drawing can be verified.
"""
import datetime as dt
import io
import json
import multiprocessing as mp
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ProcessPoolExecutor

import matplotlib
matplotlib.use('Agg')
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter, maximum_filter, minimum_filter
from shapely.geometry import box
from shapely.ops import unary_union

from gfs_latest import BUCKET, STEPS, grib_url, label, latest_run
import swell_sources

AREA = dict(w=-90, e=90, s=20, n=90)          # data we draw: well beyond the map, so colour fills it
STORE = dict(w=-55, e=50, s=35, n=85)         # data we save: well beyond the map, for the swell forecast
SALTBURN = (54.583, -0.973)
# The map: the North Sea and Saltburn's swell window, portrait. A clean crop
# just off the coasts: Iceland's west coast, Svalbard's east coast (Edgeøya)
# and north coast, and the UK's south coast (the Lizard). Turned so north is
# up along 6°E, which brings Denmark and the Skagerrak inside Svalbard's line.
# Drawn PX_W px across: sharp across a phone, with room to zoom in.
PROJ = ccrs.LambertConformal(central_longitude=6, central_latitude=63, standard_parallels=(56, 72))
MAP_NAME = 'north-sea'                          # changes with the map, so phones don't reuse old frames
PX_W, DPI = 1440, 270                           # pixels across; dots per inch sizes the text and lines to suit
MARGIN_M = 40e3                                 # sea left beyond each coast


def _at(lon, lat):
    return PROJ.transform_point(lon, lat, ccrs.PlateCarree())


EXTENT = (_at(-23.98, 64.82)[0] - MARGIN_M, _at(24.9, 77.76)[0] + MARGIN_M,     # in PROJ: x west, east,
          _at(-5.23, 50.02)[1] - MARGIN_M, _at(23.01, 80.47)[1] + MARGIN_M)     # y south, north
MAP_ASPECT = (EXTENT[1] - EXTENT[0]) / (EXTENT[3] - EXTENT[2])                  # width over height, about 0.55
FIELDS = {'PRMSL:mean sea level': 'prmsl', 'HGT:500 mb': 'gh', 'UGRD:10 m above ground': 'u10', 'VGRD:10 m above ground': 'v10'}
KN = 1.943844                                  # knots per m/s
# Frames drawn: every hour the model gives, hourly to +120 h (day 5) and then
# every 3 hours to +384 h (day 16, the end of the run). 209 frames.
DRAW_STEPS = list(range(0, 121)) + list(range(123, 385, 3))
FIRST = 168                                    # the first pass, published as soon as it's drawn; --rest adds the hours after
WAIT_MIN = 75                                  # how long a frame waits for NOAA to publish its hour
ANALYSIS_DAYS = 5                              # how far back the swell forecast starts
PUBLISHED = f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY', 'mattkirwan/north-sea-charts')}/charts/"
# The Norwegian Ice Service's latest chart of the European Arctic: drawn by
# their sea-ice analysts from satellite radar, Svalbard, the Barents Sea and
# the Fram and Denmark Straits, on weekdays (after 15 UTC).
ICE_URL = 'https://cryo.met.no/sites/cryo/files/latest/NIS_arctic_latest_pl_a.zip'

INK, PAPER, COAST = '#173242', '#E8EEF1', '#0F2230'
# Sea-level pressure, in the same 4 hPa steps as the isobars: deep purple and
# blue for lows, a light middle near average (~1013), bright orange and red
# for highs. Saturated so lows and highs stand out at a glance.
P_CMAP = LinearSegmentedColormap.from_list('mslp', [
    (0.00, '#3b0a6e'), (0.25, '#3d2fd4'), (0.45, '#1e8ff0'), (0.58, '#27c6e0'),
    (0.65, '#f4f1c6'),  # ~1013 hPa, about average
    (0.72, '#ffd23a'), (0.82, '#ff9a1f'), (0.92, '#f04a1c'), (1.00, '#a8101e')])
P_LEVELS = np.arange(940, 1053, 4)
# NOAA's wave model, the same run: significant wave height, and the model's
# separate swells (up to three: height and period of each), for the longest
# swell present (peak period where there's only wind sea, as under a storm).
# Peak period alone would hide a small long-period swell under the local wind
# waves, which is exactly the swell we're looking for.
WAVE_FIELDS = {'HTSGW:surface': 'hs', 'PERPW:surface': 'tp', **{f'SWELL:{k} in sequence': f'sh{k}' for k in (1, 2, 3)},
               **{f'SWPER:{k} in sequence': f'sp{k}' for k in (1, 2, 3)}}
LONG_MIN_M = 0.1                               # a swell smaller than this doesn't count as present
LAND = '#46525a'
# Wave height (m): calm deep blue, through teal and green to yellow, orange,
# red and purple for the biggest seas.
H_LEVELS = [0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 12, 15]
H_CMAP = LinearSegmentedColormap.from_list('hs', [
    (0.00, '#0b2350'), (0.12, '#1559b8'), (0.25, '#1f9bc2'), (0.38, '#2fbf8f'), (0.50, '#a5d65a'),
    (0.62, '#ffe14d'), (0.74, '#ffa21f'), (0.86, '#ef4b3c'), (1.00, '#9c2bb0')])
# Peak period (s): short wind sea in muted blues, groundswell in greens and
# yellows, and the rare long-period swell (16 s and up) in hot orange to magenta.
T_LEVELS = np.arange(4, 24, 1)
T_CMAP = LinearSegmentedColormap.from_list('tp', [
    (0.00, '#1a2a4a'), (0.20, '#2b4f8a'), (0.38, '#2f8fb0'), (0.50, '#36b98a'), (0.62, '#b9d84a'),
    (0.70, '#ffd23a'), (0.80, '#ff8a1f'), (0.90, '#f0306a'), (1.00, '#d020d8')])


def get(url, rng=None, timeout=60):
    req = urllib.request.Request(url, headers={'Range': f'bytes={rng[0]}-{rng[1]}'} if rng else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_idx(url):
    """A GRIB file's index, waiting up to WAIT_MIN minutes for NOAA to publish
    it: the chart job starts when the run reaches +168 h, and the later hours
    follow over the next hour or so."""
    end = time.time() + WAIT_MIN * 60
    while True:
        try:
            return get(url + '.idx').decode().splitlines()
        except urllib.error.HTTPError as e:
            if e.code not in (403, 404) or time.time() > end:
                raise
            time.sleep(60)


def fetch_fields(run, step):
    """Download just our fields for one forecast hour and decode them."""
    url = grib_url(run, step)
    idx = get_idx(url)
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


def wave_url(run, step):
    return f'{BUCKET}/gfs.{run:%Y%m%d}/{run:%H}/wave/gridded/gfswave.t{run:%H}z.global.0p25.f{step:03d}.grib2'


def fetch_waves(run, step):
    """NOAA's wave model for one forecast hour: height, peak period, and each
    separate swell's height and period, decoded and cut to the area we draw."""
    url = wave_url(run, step)
    idx = get_idx(url)
    out = {}
    for i, line in enumerate(idx):
        parts = line.split(':')
        name = f'{parts[3]}:{parts[4]}'
        if name in WAVE_FIELDS and WAVE_FIELDS[name] not in out:
            start = int(parts[1])
            end = int(idx[i + 1].split(':')[1]) - 1 if i + 1 < len(idx) else ''
            with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as f:
                f.write(get(url, (start, end)))
            ds = xr.open_dataset(f.name, engine='cfgrib', backend_kwargs={'indexpath': ''})
            var = ds[list(ds.data_vars)[0]]
            var = var.assign_coords(longitude=((var.longitude + 180) % 360) - 180).sortby('longitude')
            if var.latitude[0] < var.latitude[-1]:
                var = var.sortby('latitude', ascending=False)
            out[WAVE_FIELDS[name]] = var.sel(latitude=slice(AREA['n'], AREA['s']), longitude=slice(AREA['w'], AREA['e'])).load()
            os.unlink(f.name)
    if set(out) != set(WAVE_FIELDS.values()):
        raise RuntimeError(f'waves f{step:03d}: missing fields, found {list(out)}')
    return out


_wave_land = {}


def wave_land():
    """What every wave frame shares, made once: the land and coast as an
    image the size of the map, and where each of its pixels falls in lon/lat."""
    if not _wave_land:
        fig, ax = map_figure()
        fig.patch.set_alpha(0)
        ax.set_facecolor((0, 0, 0, 0))
        ax.add_feature(cfeature.LAND.with_scale('50m'), facecolor=LAND, edgecolor='none')
        ax.add_feature(cfeature.COASTLINE.with_scale('50m'), edgecolor=PAPER, linewidth=0.5, alpha=0.6)
        ax.axis('off')
        fig.canvas.draw()
        img = np.asarray(fig.canvas.buffer_rgba()).astype(np.float32) / 255
        x0, x1, y0, y1 = ax.get_extent()
        plt.close(fig)
        h, w = img.shape[:2]
        xs, ys = np.meshgrid(x0 + (np.arange(w) + 0.5) / w * (x1 - x0), y1 - (np.arange(h) + 0.5) / h * (y1 - y0))
        ll = ccrs.PlateCarree().transform_points(PROJ, xs.ravel(), ys.ravel())
        _wave_land.update(img=img, extent=(x0, x1, y0, y1), lon=ll[:, 0].reshape(h, w), lat=ll[:, 1].reshape(h, w))
    return _wave_land


def to_pixels(field, lons, lats, land):
    """A lon/lat field sampled at every pixel of the map (bilinear; NaN stays NaN)."""
    fi = (land['lat'] - lats[0]) / (lats[1] - lats[0])
    fj = (land['lon'] - lons[0]) / (lons[1] - lons[0])
    i0 = np.clip(np.floor(fi).astype(int), 0, len(lats) - 2)
    j0 = np.clip(np.floor(fj).astype(int), 0, len(lons) - 2)
    a, b = np.clip(fi - i0, 0, 1), np.clip(fj - j0, 0, 1)
    return ((1 - a) * (1 - b) * field[i0, j0] + (1 - a) * b * field[i0, j0 + 1] +
            a * (1 - b) * field[i0 + 1, j0] + a * b * field[i0 + 1, j0 + 1])


def to_coast(field, cells=2):
    """The wave model's sea stops a cell or two short of the coast (its grid
    is 0.25°, 28 km): carry the nearest sea value on up to the coastline, so
    the land drawn over it meets the colour cleanly. Bigger gaps, like sea
    ice, stay empty."""
    gap = ~np.isfinite(field)
    if not gap.any():
        return field
    dist, (iy, ix) = distance_transform_edt(gap, return_indices=True)
    out = field[iy, ix]
    out[dist > cells] = np.nan
    return out


def draw_waves(run, step, w, hpath, tpath):
    """Two frames from the wave model: height, and the period of the longest
    swell present (of the model's separate swells, any of LONG_MIN_M or more;
    where there's only wind sea, its peak period), each as colour over the sea
    (the app shows the scale), and for period a white line where swell of
    16 s or more has reached. Same map as the pressure charts, pixel for
    pixel; played in turn, the swell can be seen moving. The colour is worked
    out pixel by pixel from the model's grid, which is much quicker than
    drawing contours."""
    hs = w['hs'].values
    per = np.stack([np.where(np.nan_to_num(w[f'sh{k}'].values) >= LONG_MIN_M, w[f'sp{k}'].values, np.nan) for k in (1, 2, 3)])
    tp = np.where(np.isfinite(hs), np.nan_to_num(np.nanmax(np.where(np.isfinite(per), per, -1), axis=0), nan=-1), np.nan)
    tp = np.where(tp > 0, tp, w['tp'].values)  # no swell, only wind sea: its peak period
    lons, lats = w['hs'].longitude.values, w['hs'].latitude.values
    if np.nanmax(hs) > 25 or np.nanmax(tp) > 35:
        raise RuntimeError(f'waves f{step:03d}: implausible, {np.nanmax(hs):.1f} m, {np.nanmax(tp):.0f} s')
    land = wave_land()
    ink = np.array(matplotlib.colors.to_rgba(INK))
    valid = run + dt.timedelta(hours=step)
    for field, levels, cmap, label_, unit, path in ((hs, H_LEVELS, H_CMAP, 'Wave height', 'm', hpath),
                                                     (tp, T_LEVELS, T_CMAP, 'Longest swell period', 's', tpath)):
        norm = BoundaryNorm(levels, cmap.N, extend='max')
        px = to_pixels(to_coast(field), lons, lats, land)
        rgba = cmap(norm(np.nan_to_num(px, nan=levels[0])))
        rgba[~np.isfinite(px)] = ink
        rgba[..., :3] = rgba[..., :3] * (1 - land['img'][..., 3:]) + land['img'][..., :3] * land['img'][..., 3:]
        fig, ax = map_figure()
        ax.imshow(rgba, extent=land['extent'], origin='upper', transform=PROJ, interpolation='nearest', zorder=2)
        ax.set_extent(land['extent'], crs=PROJ)
        if unit == 's':
            cs = ax.contour(lons, lats, gaussian_filter(np.nan_to_num(field), 1), levels=[16], colors='white', linewidths=1.3,
                            transform=ccrs.PlateCarree(), zorder=4)
            for t in ax.clabel(cs, fmt='%d s', fontsize=9, inline=True, colors='white'):
                t.set_path_effects([pe.withStroke(linewidth=2.5, foreground=COAST)])
        ax.text(0.988, 0.006, f'{label_} ({unit}), NOAA wave model\nrun {run:%Hz %d %b} +{step}h · valid {valid:%a %d %b %H}z',
                transform=ax.transAxes, ha='right', va='bottom', color=PAPER, fontsize=6, zorder=6,
                path_effects=[pe.withStroke(linewidth=2, foreground=INK)])
        ax.axis('off')
        save_png(fig, path, facecolor=INK)
    return float(np.nanmax(hs)), float(np.nanmax(tp))


def save_fields(run, steps, frames, path):
    """The run's sea-level pressure and 500 hPa height on the 0.25° grid over
    STORE, every frame, as whole numbers: pressure in tenths of a hPa, height
    in metres and 10 m wind (u east, v north) in tenths of a m/s (int16, compressed)."""
    crop = lambda v: v.sel(latitude=slice(STORE['n'], STORE['s']), longitude=slice(STORE['w'], STORE['e']))
    first = crop(frames[0]['prmsl'])
    np.savez_compressed(
        path, run=run.strftime('%Y-%m-%dT%HZ'), steps=np.array(steps, dtype=np.int16),
        lat=first.latitude.values.astype(np.float32), lon=first.longitude.values.astype(np.float32),
        mslp_dhpa=np.stack([np.rint(crop(f['prmsl']).values / 10) for f in frames]).astype(np.int16),
        z500_m=np.stack([np.rint(crop(f['gh']).values) for f in frames]).astype(np.int16),
        u10_dms=np.stack([np.rint(crop(f['u10']).values * 10) for f in frames]).astype(np.int16),
        v10_dms=np.stack([np.rint(crop(f['v10']).values * 10) for f in frames]).astype(np.int16))


def keep_analyses(run, frames_path, out_path):
    """The 10 m winds at the start of every run over the last ANALYSIS_DAYS,
    at 0.5°, for the swell forecast to start from: swell made before a run
    starts is still arriving for days after. Adds this run's to those
    published with the last run (analyses.npz, or failing that its
    fields.npz). Returns them all, before and including this run's."""
    run = run.replace(tzinfo=None)  # the stored times are plain UTC
    now = swell_sources.winds_from_npz(np.load(frames_path), 2)
    past = None
    for name, every in (('analyses.npz', 1), ('fields.npz', 2)):
        try:
            past = swell_sources.winds_from_npz(np.load(io.BytesIO(get(PUBLISHED + name, timeout=120))), every)
            break
        except Exception as e:
            print(f'  No earlier {name}: {e}')
    times, u, v = [now['times'][0]], [now['u'][0]], [now['v'][0]]
    if past and past['u'].shape[1:] == now['u'].shape[1:]:
        keep = [k for k, t in enumerate(past['times']) if run - dt.timedelta(days=ANALYSIS_DAYS) <= t < run]
        if 'analyses' not in name:
            keep = keep[:1]  # just the earlier run's own start; the rest is forecast
        times = [past['times'][k] for k in keep] + times
        u, v = [past['u'][k] for k in keep] + u, [past['v'][k] for k in keep] + v
    np.savez_compressed(out_path, times=np.array([int((t - dt.datetime(1970, 1, 1)).total_seconds() * 1000) for t in times], dtype=np.int64),
                        lat=now['lat'].astype(np.float32), lon=now['lon'].astype(np.float32),
                        u10_dms=np.rint(np.stack(u) * 10).astype(np.int16), v10_dms=np.rint(np.stack(v) * 10).astype(np.int16))
    print(f'  analyses.npz: {len(times)} run starts from {times[0]:%d %H}z, {os.path.getsize(out_path) // 1024} KB')
    return swell_sources.join_winds(swell_sources.winds_from_npz(np.load(out_path)), now)


def write_grid(path):
    """Where each whole 2° of latitude and longitude falls on the chart, as
    fractions of its width and height from the top left, so the app can draw
    its own lines (the swell travel times) exactly on the map by
    interpolating."""
    x0, x1, y0, y1 = EXTENT
    lons, lats = np.arange(-60, 72, 2.0), np.arange(30, 90, 2.0)
    lon, lat = np.meshgrid(lons, lats)
    xy = PROJ.transform_points(ccrs.PlateCarree(), lon, lat)
    fx, fy = (xy[..., 0] - x0) / (x1 - x0), (y1 - xy[..., 1]) / (y1 - y0)
    with open(path, 'w') as fh:
        json.dump(dict(lon0=float(lons[0]), lat0=float(lats[0]), step=2.0, nlon=len(lons), nlat=len(lats),
                       fx=[round(float(v), 5) for v in fx.ravel()], fy=[round(float(v), 5) for v in fy.ravel()]), fh)


def extrema(field, lons, lats, size, kind):
    """Local highs or lows in a smoothed field, away from the edges."""
    sm = gaussian_filter(field, 3)
    filt = maximum_filter if kind == 'H' else minimum_filter
    peaks = np.argwhere(sm == filt(sm, size=size, mode='nearest'))
    wide = filt(sm, size=size * 2, mode='nearest')  # keep only centres that dominate a wider area
    x0, x1, y0, y1 = EXTENT
    mx, my = (x1 - x0) * 0.03, (y1 - y0) * 0.04  # and more at the bottom, clear of the caption
    out = []
    for y, x in peaks:
        if 8 < y < field.shape[0] - 8 and 8 < x < field.shape[1] - 8 and abs(sm[y, x] - wide[y, x]) < 0.6:
            lo, la = float(lons[x]), float(lats[y])
            px, py = PROJ.transform_point(lo, la, ccrs.PlateCarree())
            if x0 + mx <= px <= x1 - mx and y0 + 2.5 * my <= py <= y1 - my:  # whole label inside the map
                out.append((lo, la, float(field[y, x])))
    return out


def map_figure():
    """A figure exactly the map's shape (no empty margins), PX_W pixels
    across. Every layer uses it, so they line up pixel for pixel."""
    width = PX_W / DPI
    fig = plt.figure(figsize=(width, width / MAP_ASPECT), dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1], projection=PROJ)
    ax.set_extent(EXTENT, crs=PROJ)
    return fig, ax


def save_png(fig, path, **kw):
    fig.savefig(path, **kw)
    plt.close(fig)
    # 256 colours is plenty for these flat bands, lines and arrows, at about a third of the size.
    im = Image.open(path)
    im = im.convert('RGBA' if im.mode in ('RGBA', 'LA') else 'RGB')
    im.quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(path, optimize=True)


def draw(run, step, f, path):
    p = f['prmsl'].values / 100.0                  # Pa -> hPa
    lons, lats = f['prmsl'].longitude.values, f['prmsl'].latitude.values
    fig, ax = map_figure()
    ax.set_facecolor(INK)
    ps = gaussian_filter(p, 1.0)
    cf = ax.contourf(lons, lats, ps, levels=P_LEVELS, cmap=P_CMAP, extend='both', transform=ccrs.PlateCarree(), zorder=2, antialiased=False)
    cf.set_edgecolor('face')  # fill the hairline seams between bands
    ax.add_feature(cfeature.COASTLINE.with_scale('50m'), edgecolor=COAST, linewidth=0.9, zorder=3)
    ax.add_feature(cfeature.BORDERS.with_scale('50m'), edgecolor=COAST, linewidth=0.4, alpha=0.5, zorder=3)
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
    valid = run + dt.timedelta(hours=step)
    ax.text(0.988, 0.006, f'NOAA GFS · run {run:%Hz %d %b} +{step}h · valid {valid:%a %d %b %H}z', transform=ax.transAxes,
            ha='right', va='bottom', color=COAST, fontsize=6, zorder=6)
    ax.axis('off')
    save_png(fig, path, facecolor=INK)
    return p, lons, lats


ice_tenths = swell_sources.ice_tenths


def draw_ice(outdir):
    """The sea ice as a transparent layer the size of the charts: white,
    more solid where the ice is closer packed, with the ice edge outlined.
    Waves can't build over it. Returns the chart's date and the close-packed
    ice (for the swell forecast), or None, None if the chart couldn't be had
    (the charts publish without it)."""
    try:
        data = get(ICE_URL, timeout=120)
        zpath = os.path.join(outdir, 'ice.zip')
        with open(zpath, 'wb') as fh:
            fh.write(data)
        tmp = tempfile.mkdtemp()
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        shp = next(os.path.join(tmp, n) for n in os.listdir(tmp) if n.endswith('.shp'))
        date = next(t for t in os.path.basename(shp).split('_') if t.isdigit() and len(t) == 8)
        fig, ax = map_figure()
        fig.patch.set_alpha(0)
        ax.set_facecolor((0, 0, 0, 0))
        # The chart's areas run under the coast (it's drawn with land on top),
        # so cut the land out, using the same coastline as the charts.
        area = box(-60, 55, 90, 90)
        land = unary_union([g.buffer(0) for g in shpreader.Reader(shpreader.natural_earth('50m', 'physical', 'land')).geometries()
                            if g.intersects(area)]).intersection(area)
        ice, dense, counts = [], [], {}
        for rec in shpreader.Reader(shp).records():
            tenths = ice_tenths(rec.attributes.get('CT'))
            name = str(rec.attributes.get('NIS_CLASS', '')).strip() or str(rec.attributes.get('CT'))
            counts[name] = counts.get(name, 0) + 1
            if tenths is None or rec.geometry is None:
                continue
            g = rec.geometry.buffer(0).difference(land)
            if g.is_empty:
                continue
            ice.append(g)
            if tenths >= swell_sources.ICE_TENTHS:
                dense.append(g)
            ax.add_geometries([g], ccrs.PlateCarree(), facecolor=(1, 1, 1, 0.3 + 0.6 * tenths / 10),
                              edgecolor='none', zorder=3)
        if not ice:
            raise RuntimeError('no ice polygons in the chart')
        edge = unary_union(ice)
        ax.add_geometries([edge], ccrs.PlateCarree(), facecolor='none', edgecolor='#0F2230', linewidth=1.2, zorder=4)
        ax.add_geometries([edge], ccrs.PlateCarree(), facecolor='none', edgecolor='white', linewidth=0.5, zorder=5)
        ax.axis('off')
        save_png(fig, os.path.join(outdir, 'ice.png'), transparent=True)
        print(f'  ice.png: chart of {date}, {len(ice)} ice areas; classes {counts}')
        return f'{date[:4]}-{date[4:6]}-{date[6:]}', unary_union(dense) if dense else None
    except Exception as e:  # the ice is a nice-to-have; never hold the charts up for it
        print(f'  No ice layer this run: {e}')
        for n in ('ice.zip', 'ice.png'):
            if os.path.exists(os.path.join(outdir, n)):
                os.unlink(os.path.join(outdir, n))
        return None, None


def sanity(step, p):
    # Catches broken data (wrong units, missing values), not weather: sea-level
    # pressure over Greenland's ice and Siberia's winter highs passes 1080 hPa
    # (the record is 1084, in Mongolia), and the map takes both in.
    lo, hi = float(np.nanmin(p)), float(np.nanmax(p))
    if np.isnan(p).any() or lo < 870 or hi > 1095:
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


def render_step(args):
    """One frame, start to finish, in a worker process: fetch the run's fields
    for the hour, draw the pressure chart, and the wave layer if NOAA has it. Returns the numbers main() needs, and the fields themselves
    every 6 hours (for the data kept, the alerts and our own forecast)."""
    run, step, outdir = args
    f = fetch_fields(run, step)
    p, _, _ = draw(run, step, f, os.path.join(outdir, f'f{step:03d}.png'))
    lo, hi = sanity(step, p)
    out = dict(step=step, lo=lo, hi=hi, waves=None, wave_error=None, fields=f if step % 6 == 0 else None)
    try:  # the wave layer never holds the charts up
        out['waves'] = draw_waves(run, step, fetch_waves(run, step), os.path.join(outdir, f'h{step:03d}.png'), os.path.join(outdir, f't{step:03d}.png'))
    except Exception as e:
        out['wave_error'] = str(e)
    return out


def render_all(run, steps, outdir, safe=False):
    """Every frame drawn on its own core (four on GitHub's runners), in order.
    The map features and the wave layer's land are made first, so each worker
    starts with them rather than all fetching them at once. safe: a frame that
    fails comes back as None rather than stopping the rest."""
    for feat in (cfeature.COASTLINE, cfeature.BORDERS, cfeature.LAND):
        list(feat.with_scale('50m').geometries())
    wave_land()
    with ProcessPoolExecutor(max_workers=min(4, os.cpu_count() or 1), mp_context=mp.get_context('fork')) as pool:
        out = list(pool.map(render_safe if safe else render_step, [(run, step, outdir) for step in steps]))
    return {s: r for s, r in zip(steps, out)}


def render_safe(args):
    try:
        return render_step(args)
    except Exception as e:
        print(f'  f{args[1]:03d}: {e}')
        return None


def rest(outdir):
    """The second pass: the hours after FIRST, added to the charts the first
    pass published, up to the first hour that couldn't be drawn (NOAA may not
    have it yet). The wave layer goes as far as the charts if every hour of it
    was drawn; otherwise the charts stop where it stops."""
    with open(os.path.join(outdir, 'manifest.json')) as fh:
        manifest = json.load(fh)
    run = dt.datetime.fromtimestamp(manifest['run'] / 1000, dt.timezone.utc).replace(tzinfo=None)
    steps = [s for s in DRAW_STEPS if s > max(manifest['steps'])]
    done = render_all(run, steps, outdir, safe=True)
    added = []
    for s in steps:
        r = done[s]
        if not r or (manifest.get('waves') and not r['waves']):
            break
        added.append(s)
        manifest['pressure']['min'] = min(manifest['pressure']['min'], round(r['lo']))
        manifest['pressure']['max'] = max(manifest['pressure']['max'], round(r['hi']))
    manifest['steps'] += added
    with open(os.path.join(outdir, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh)
    print(f"Added {len(added)} of {len(steps)} later frames, to +{manifest['steps'][-1]} h")


def main():
    outdir = sys.argv[1]
    do_check = '--check' in sys.argv
    os.makedirs(outdir, exist_ok=True)
    if '--rest' in sys.argv:
        return rest(outdir)
    steps = [0, 24, 72] if os.environ.get('QUICK') else [s for s in DRAW_STEPS if s <= FIRST]  # QUICK: a preview of the look
    run = latest_run()
    print(f'GFS run {run:%Y-%m-%d %H}z')
    # The workflow passes the run already published; nothing to do if it's this one.
    if os.environ.get('PUBLISHED_RUN') == label(run) and not do_check and not os.environ.get('FORCE'):
        print('Already published; nothing to do.')
        return
    done = render_all(run, steps, outdir)
    lows, highs, frames = [], [], []
    waves_ok = all(done[s]['waves'] for s in steps)
    for step in steps:
        r = done[step]
        lows.append(r['lo']); highs.append(r['hi'])
        print(f"  f{step:03d}: {r['lo']:.0f}-{r['hi']:.0f} hPa; " +
              (f"waves up to {r['waves'][0]:.1f} m, {r['waves'][1]:.0f} s" if r['waves'] else f"no wave layer ({r['wave_error']})"))
        if r['fields'] is not None:
            frames.append(r['fields'])
            if do_check and step in (0, 24, 72, 120):
                f = r['fields']
                check(run, step, f['prmsl'].values / 100.0, f['prmsl'].longitude.values, f['prmsl'].latitude.values,
                      os.path.join(outdir, f'f{step:03d}.png'), outdir)
    # The data kept, the alerts and our own forecast go every 6 hours, as before.
    steps6 = [s for s in steps if s % 6 == 0]
    save_fields(run, steps6, frames, os.path.join(outdir, 'fields.npz'))
    winds = None
    try:
        winds = keep_analyses(run, os.path.join(outdir, 'fields.npz'), os.path.join(outdir, 'analyses.npz'))
    except Exception as e:
        print(f'  No analyses kept this run: {e}')
    ice_date, dense_ice = draw_ice(outdir)
    write_grid(os.path.join(outdir, 'grid.json'))
    # Saltburn's swell window, bomb lows sending swell our way, and our swell
    # forecast. None of them ever holds the charts up.
    window, alerts, forecast = None, [], None
    try:
        window = swell_sources.swell_window()
        with open(os.path.join(outdir, 'window.json'), 'w') as fh:
            json.dump(window, fh)
        print(f'  window.json: open past 1000 km on {swell_sources.open_sectors(window, 1000)}')
        alerts = swell_sources.storm_alerts(run, steps6, frames, window) if len(steps6) > 4 else []
        for a in alerts:
            print(f"  alert: {a['hPa']} hPa {a['where']}, {a['drop24']} hPa in 24 h; pulses {[(p['where'], p['kn']) for p in a['pulses']]}")
    except Exception as e:
        print(f'  No swell window or alerts this run: {e}')
    try:
        if window and winds and len(steps6) > 4:
            series, events = swell_sources.swell_forecast(run, winds, window, dense_ice)
            with open(os.path.join(outdir, 'forecast.json'), 'w') as fh:
                json.dump(swell_sources.forecast_json(run, series, events), fh)
            forecast = 'forecast.json'
            for e in events:
                print(f"  swell: peak {e['peak']:%a %d %H}z {e['ft']:.1f} ft ({e['h']:.1f} m {e['p']:.0f} s from {e['d']}) from {e['where']}")
    except Exception as e:
        print(f'  No swell forecast this run: {e}')
    print(f'  fields.npz: {os.path.getsize(os.path.join(outdir, "fields.npz")) // 1024} KB')
    manifest = dict(run=int(run.timestamp() * 1000), runLabel=label(run), steps=steps, file='f%03d.png', data='fields.npz', map=MAP_NAME, grid='grid.json',
                    window='window.json' if window else None, alerts=alerts, forecast=forecast,
                    waves=dict(height='h%03d.png', period='t%03d.png', source='NOAA GFS-Wave 0.25°') if waves_ok else None,
                    ice=dict(file='ice.png', date=ice_date) if ice_date else None,
                    generated=int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000), source='NOAA GFS 0.25°',
                    pressure=dict(min=round(min(lows)), max=round(max(highs))))
    with open(os.path.join(outdir, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh)
    print(f'Wrote {len(steps)} charts, the wave layer and manifest.json')


if __name__ == '__main__':
    main()
