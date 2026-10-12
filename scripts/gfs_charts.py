"""Draw our own North Sea pressure charts from NOAA's GFS model.

For the newest complete GFS run, downloads sea-level pressure and 500 hPa
geopotential height for each forecast hour (0-168, every 6 h) from NOAA's open
data on AWS, using the .idx files to fetch just those two fields, and draws a
chart per hour: sea-level pressure as bright colour (blues and purples for
lows, oranges and reds for highs) with isobars every 4 hPa, H/L centres and
coastlines. (500 hPa height is downloaded for the checks but not drawn.) Writes PNGs and manifest.json into the output folder,
plus ice.png, a transparent sea-ice layer from the latest ice chart (see draw_ice), with ice.zip, the chart itself;
plus a matching transparent wind layer per hour (w000.png...): 10 m wind as
arrows the way it blows, longer for stronger, which the app can lay over the chart;
plus fields.npz: the run's numbers themselves for the charted area, so we
keep the data as well as the pictures (see save_fields).

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
import zipfile

import matplotlib
matplotlib.use('Agg')
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image
from scipy.ndimage import gaussian_filter, maximum_filter, minimum_filter
from shapely.ops import unary_union

from gfs_latest import STEPS, grib_url, label, latest_run

AREA = dict(w=-90, e=90, s=20, n=90)          # data we draw: well beyond the map, so colour fills it
STORE = dict(w=-55, e=50, s=35, n=85)         # data we save: the map with a margin
# Map extent (lon W, lon E, lat S, lat N): out west over Iceland into the
# Atlantic for lows on their way, all of Svalbard, and down to Biscay.
VIEW = [-40, 35, 42, 82]
HOME = [-20, 20, 49, 78]                       # the app's default framing: the North Sea, as the map used to be
SALTBURN = (54.583, -0.973)
PROJ = ccrs.LambertConformal(central_longitude=5, central_latitude=62, standard_parallels=(55, 70))
FIELDS = {'PRMSL:mean sea level': 'prmsl', 'HGT:500 mb': 'gh', 'UGRD:10 m above ground': 'u10', 'VGRD:10 m above ground': 'v10'}
KN = 1.943844                                  # knots per m/s
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


def get(url, rng=None, timeout=60):
    req = urllib.request.Request(url, headers={'Range': f'bytes={rng[0]}-{rng[1]}'} if rng else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


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


def map_box(box):
    """The projected rectangle that set_extent(box) shows."""
    probe = plt.figure()
    ax = probe.add_axes([0, 0, 1, 1], projection=PROJ)
    ax.set_extent(box, crs=ccrs.PlateCarree())
    ext = ax.get_extent()
    plt.close(probe)
    return ext


def home_view():
    """Where HOME sits in the map, as the app's crop: centre (fractions of
    width and height from the top left), visible height, and its width."""
    x0, x1, y0, y1 = map_box(VIEW)
    h0, h1, k0, k1 = map_box(HOME)
    return dict(cx=round(((h0 + h1) / 2 - x0) / (x1 - x0), 4), cy=round((y1 - (k0 + k1) / 2) / (y1 - y0), 4),
                span=round((k1 - k0) / (y1 - y0), 4), w=round((h1 - h0) / (x1 - x0), 4))


def extrema(field, lons, lats, size, kind):
    """Local highs or lows in a smoothed field, away from the edges."""
    sm = gaussian_filter(field, 3)
    filt = maximum_filter if kind == 'H' else minimum_filter
    peaks = np.argwhere(sm == filt(sm, size=size, mode='nearest'))
    wide = filt(sm, size=size * 2, mode='nearest')  # keep only centres that dominate a wider area
    x0, x1, y0, y1 = map_box(VIEW)
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
    """A figure exactly the map's shape (no empty margins). 11 in at 155 dpi:
    about 1700 px across, so the North Sea framing the app opens on is as
    sharp as the old North Sea-only chart. The wind layer uses the same, so
    the two line up pixel for pixel."""
    x0, x1, y0, y1 = map_box(VIEW)
    width = 11.0
    fig = plt.figure(figsize=(width, width * (y1 - y0) / (x1 - x0)), dpi=155)
    ax = fig.add_axes([0, 0, 1, 1], projection=PROJ)
    ax.set_extent(VIEW, crs=ccrs.PlateCarree())
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
    ax.plot(SALTBURN[1], SALTBURN[0], 'o', ms=6, color='#FFC23D', mec=COAST, mew=1, transform=ccrs.PlateCarree(), zorder=6)
    valid = run + dt.timedelta(hours=step)
    ax.text(0.012, 0.008, f'Run {run:%Hz %d %b} +{step}h · valid {valid:%a %d %b %H}z', transform=ax.transAxes,
            color=COAST, fontsize=9, zorder=6)
    ax.axis('off')
    save_png(fig, path, facecolor=INK)
    return p, lons, lats


def draw_wind(step, f, path):
    """10 m wind as arrows on a transparent layer the size of the chart: evenly
    spaced across the map, pointing the way the wind blows, length in
    proportion to speed (a key arrow shows 30 kn). Calm spots get none."""
    u, v = f['u10'].values * KN, f['v10'].values * KN
    lons, lats = f['u10'].longitude.values, f['u10'].latitude.values
    speed = np.hypot(u, v)
    if np.isnan(speed).any() or speed.max() > 200:
        raise RuntimeError(f'f{step:03d}: implausible wind, max {np.nanmax(speed):.0f} kn')
    calm = speed < 6  # light enough not to matter, and only an arrowhead at this size
    u, v = np.where(calm, np.nan, u), np.where(calm, np.nan, v)
    fig, ax = map_figure()
    fig.patch.set_alpha(0)
    ax.set_facecolor((0, 0, 0, 0))
    q = ax.quiver(lons, lats, u, v, transform=ccrs.PlateCarree(), regrid_shape=24, pivot='middle',
                  scale=75, scale_units='inches', width=0.0026, headwidth=3.6, headlength=4.2, headaxislength=3.8,
                  color='white', edgecolor='#0F2230', linewidth=0.7, zorder=5)
    k = ax.quiverkey(q, 0.955, 0.035, 30, '30 kn', labelpos='W', coordinates='axes', color='white',
                     fontproperties=dict(size=10, weight='bold'), labelcolor='#0F2230')
    k.text.set_path_effects([pe.withStroke(linewidth=3, foreground='white')])
    ax.axis('off')
    save_png(fig, path, transparent=True)
    return float(np.nanmax(speed))


def ice_tenths(ct):
    """Total concentration from a SIGRID-3 CT code, in tenths: 01 ice free and
    02 open water (under a tenth) are None; 13 is 1-3 tenths, 46 4-6, 79 7-9,
    91 9-10, 92 10, 10..90 that many tenths; 98 (icebergs only) None."""
    try:
        v = int(str(ct).strip())
    except ValueError:
        return None
    if v < 10 or v > 92:
        return None
    if v == 91:
        return 9.5
    if v == 92:
        return 10.0
    lo, hi = divmod(v, 10)
    return float(lo) if hi == 0 else (lo + hi) / 2


def draw_ice(outdir):
    """The sea ice as a transparent layer the size of the charts: white,
    more solid where the ice is closer packed, with the ice edge outlined.
    Waves can't build over it. Returns the chart's date, or None if the
    chart couldn't be had (the charts publish without it)."""
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
        ice, counts = [], {}
        for rec in shpreader.Reader(shp).records():
            tenths = ice_tenths(rec.attributes.get('CT'))
            name = str(rec.attributes.get('NIS_CLASS', '')).strip() or str(rec.attributes.get('CT'))
            counts[name] = counts.get(name, 0) + 1
            if tenths is None or rec.geometry is None:
                continue
            ice.append(rec.geometry)
            ax.add_geometries([rec.geometry], ccrs.PlateCarree(), facecolor=(1, 1, 1, 0.3 + 0.6 * tenths / 10),
                              edgecolor='none', zorder=3)
        if not ice:
            raise RuntimeError('no ice polygons in the chart')
        edge = unary_union([g.buffer(0) for g in ice])
        ax.add_geometries([edge], ccrs.PlateCarree(), facecolor='none', edgecolor='#0F2230', linewidth=1.2, zorder=4)
        ax.add_geometries([edge], ccrs.PlateCarree(), facecolor='none', edgecolor='white', linewidth=0.5, zorder=5)
        ax.axis('off')
        save_png(fig, os.path.join(outdir, 'ice.png'), transparent=True)
        print(f'  ice.png: chart of {date}, {len(ice)} ice areas; classes {counts}')
        return f'{date[:4]}-{date[4:6]}-{date[6:]}'
    except Exception as e:  # the ice is a nice-to-have; never hold the charts up for it
        print(f'  No ice layer this run: {e}')
        for n in ('ice.zip', 'ice.png'):
            if os.path.exists(os.path.join(outdir, n)):
                os.unlink(os.path.join(outdir, n))
        return None


def sanity(step, p):
    lo, hi = float(np.nanmin(p)), float(np.nanmax(p))
    if np.isnan(p).any() or lo < 900 or hi > 1070:
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
    print(f'GFS run {run:%Y-%m-%d %H}z; home view {home_view()}')
    # The workflow passes the run already published; nothing to do if it's this one.
    if os.environ.get('PUBLISHED_RUN') == label(run) and not do_check and not os.environ.get('FORCE'):
        print('Already published; nothing to do.')
        return
    lows, highs, frames = [], [], []
    for step in steps:
        f = fetch_fields(run, step)
        frames.append(f)
        path = os.path.join(outdir, f'f{step:03d}.png')
        p, lons, lats = draw(run, step, f, path)
        lo, hi = sanity(step, p)
        lows.append(lo); highs.append(hi)
        wpath = os.path.join(outdir, f'w{step:03d}.png')
        top = draw_wind(step, f, wpath)
        print(f'  f{step:03d}: {lo:.0f}-{hi:.0f} hPa, {os.path.getsize(path) // 1024} KB; wind to {top:.0f} kn, {os.path.getsize(wpath) // 1024} KB')
        if do_check and step in (0, 24, 72, 120):
            check(run, step, p, lons, lats, path, outdir)
    save_fields(run, steps, frames, os.path.join(outdir, 'fields.npz'))
    ice_date = draw_ice(outdir)
    print(f'  fields.npz: {os.path.getsize(os.path.join(outdir, "fields.npz")) // 1024} KB')
    manifest = dict(run=int(run.timestamp() * 1000), runLabel=label(run), steps=steps, file='f%03d.png', wind='w%03d.png', data='fields.npz', home=home_view(),
                    ice=dict(file='ice.png', date=ice_date) if ice_date else None,
                    generated=int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000), source='NOAA GFS 0.25°',
                    pressure=dict(min=round(min(lows)), max=round(max(highs))))
    with open(os.path.join(outdir, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh)
    print(f'Wrote {len(steps)} charts, wind layers and manifest.json')


if __name__ == '__main__':
    main()
