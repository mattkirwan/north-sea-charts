"""Where swell can reach Saltburn from, and which storms are sending it.

Two things for the chart job (gfs_charts.py), from the same GFS run:

swell_window() casts rays out from just off Saltburn every half degree, along
great circles (the paths swell takes), until each meets land: Natural Earth's
1:10m coastline, so Orkney, Shetland and the Fraserburgh corner are all in
the way where they should be. The result is how far open sea runs in each
direction: the swell window. The app shades it, and the travel times only
run where it's open.

storm_alerts() follows every low through the run and flags bombs (pressure
falling at least 24 hPa in 24 hours, scaled for latitude, as forecasters
define it) whose winds are aimed at Saltburn: straight down the window, or
into the gaps north of Scotland (between Orkney and Shetland, and north of
Shetland), which some swell gets through to come on down the North Sea. For
those it works out when swell would arrive: the first long-period energy and
the main pulse, from the deep-water group speed g*T/4pi.

Standard library, numpy, scipy and shapely (all installed with cartopy).

  python scripts/swell_sources.py fields.npz   # try it on a saved run
"""
import datetime as dt
import io
import json
import os
import sys
import tempfile
import urllib.request
import zipfile

import numpy as np
import shapefile  # pyshp, comes with cartopy
import shapely
from scipy.ndimage import gaussian_filter, minimum_filter
from shapely.geometry import box, shape
from shapely.ops import unary_union

SALTBURN = (54.5838, -0.9724)
ORIGIN = (54.605, -0.955)     # rays start a little off the pier, in the sea
LAND_URL = 'https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip'
STEP_DEG, MAX_KM, RAY_KM = 0.5, 3500, 4
# The ways in north of Scotland for swell from out west: the Fair Isle gap
# (Orkney to Shetland) and north of Shetland.
GAPS = [(59.45, -1.75), (61.0, -0.4)]
KN = 1.943844
R = 6371.0


def cg_kmh(period):
    """Deep-water group speed of swell of this period, km/h."""
    return 9.81 * period / (4 * np.pi) * 3.6


def gc_dist(a_lat, a_lon, b_lat, b_lon):
    r = np.radians
    return 2 * R * np.arcsin(np.sqrt(np.sin((r(b_lat) - r(a_lat)) / 2) ** 2 +
                                     np.cos(r(a_lat)) * np.cos(r(b_lat)) * np.sin((r(b_lon) - r(a_lon)) / 2) ** 2))


def bearing(a_lat, a_lon, b_lat, b_lon):
    """Initial bearing from a to b, degrees."""
    r = np.radians
    y = np.sin(r(b_lon - a_lon)) * np.cos(r(b_lat))
    x = np.cos(r(a_lat)) * np.sin(r(b_lat)) - np.sin(r(a_lat)) * np.cos(r(b_lat)) * np.cos(r(b_lon - a_lon))
    return (np.degrees(np.arctan2(y, x)) + 360) % 360


def destination(lat, lon, brg, km):
    r = np.radians
    d, b, f1 = km / R, r(brg), r(lat)
    f2 = np.arcsin(np.sin(f1) * np.cos(d) + np.cos(f1) * np.sin(d) * np.cos(b))
    l2 = r(lon) + np.arctan2(np.sin(b) * np.sin(d) * np.cos(f1), np.cos(d) - np.sin(f1) * np.sin(f2))
    return np.degrees(f2), (np.degrees(l2) + 540) % 360 - 180


_land = None


def land():
    """Natural Earth 1:10m land around the North Sea and North Atlantic."""
    global _land
    if _land is None:
        cache = os.path.join(tempfile.gettempdir(), 'ne_10m_land.zip')
        if not os.path.exists(cache):
            with urllib.request.urlopen(LAND_URL, timeout=120) as r, open(cache, 'wb') as fh:
                fh.write(r.read())
        z = zipfile.ZipFile(cache)
        name = next(n for n in z.namelist() if n.endswith('.shp'))[:-4]
        rd = shapefile.Reader(shp=io.BytesIO(z.read(name + '.shp')), shx=io.BytesIO(z.read(name + '.shx')),
                              dbf=io.BytesIO(z.read(name + '.dbf')))
        area = box(-75, 30, 75, 89)
        parts = []
        for s in rd.shapes():
            g = shape(s.__geo_interface__)
            if g.intersects(area):
                parts.append(g.buffer(0).intersection(area))
        _land = unary_union(parts)
        shapely.prepare(_land)
    return _land


def swell_window():
    """Open sea from just off Saltburn: km to the first land along each
    bearing (0, 0.5, ... 359.5 degrees), up to MAX_KM."""
    bearings = np.arange(0, 360, STEP_DEG)
    dists = np.arange(RAY_KM, MAX_KM + RAY_KM, RAY_KM)
    B, D = np.meshgrid(bearings, dists, indexing='ij')
    la, lo = destination(ORIGIN[0], ORIGIN[1], B, D)
    hit = shapely.contains_xy(land(), lo, la)
    reach = np.where(hit.any(axis=1), dists[np.argmax(hit, axis=1)] - RAY_KM, MAX_KM).astype(float)
    return dict(origin=list(ORIGIN), step=STEP_DEG, maxKm=MAX_KM, reach=[int(v) for v in reach])


def open_sectors(window, min_km=600):
    """The window's open stretches (bearing ranges reaching at least min_km)."""
    reach, step = np.array(window['reach']), window['step']
    ok = reach >= min_km
    if ok.all():
        return [(0.0, 360.0)]
    start = int(np.argmin(ok))  # begin on a closed bearing so a range can wrap past north
    out, run = [], None
    for k in range(len(ok) + 1):
        i = (start + k) % len(ok)
        if ok[i] and run is None:
            run = i
        elif not ok[i] and run is not None:
            out.append((run * step, ((i - 1) % len(ok)) * step))
            run = None
    return out


def place(lat, lon):
    """Roughly where a low is, in words."""
    boxes = [
        ('the Denmark Strait', 64, 68.5, -36, -22), ('north of Iceland', 66.5, 71, -25, -10),
        ('south of Iceland', 58, 64, -30, -13), ('between Iceland and the Faroes', 61, 66.5, -15, -5),
        ('near Jan Mayen', 69, 73.5, -14, -3), ('the Norwegian Sea', 62, 72, -6, 12),
        ('the Greenland Sea', 72, 80, -20, 0), ('near Svalbard', 74, 82, 0, 32), ('the Barents Sea', 68, 79, 20, 60),
        ('off Norway', 57, 64, 2, 12), ('the northern North Sea', 56, 62, -3, 4),
        ('west of Scotland', 54, 60, -20, -6), ('south of Greenland', 55, 62, -50, -36), ('off Greenland', 60, 75, -60, -30),
        ('the mid-Atlantic', 40, 58, -50, -20)]
    for name, s, n, w, e in boxes:
        if s <= lat <= n and w <= lon <= e:
            return name
    return f'{abs(lat):.0f}°{"N" if lat >= 0 else "S"} {abs(lon):.0f}°{"W" if lon < 0 else "E"}'


def find_lows(p, lats, lons):
    """Lows under 1000 hPa on a 1° grid: (lat, lon, hPa)."""
    sm = gaussian_filter(p, 1.0)
    pts = np.argwhere((sm == minimum_filter(sm, size=9, mode='nearest')) & (sm < 1000))
    return [(float(lats[i]), float(lons[j]), float(p[i, j])) for i, j in pts
            if 40 <= lats[i] <= 82 and -60 <= lons[j] <= 45 and 2 < i < len(lats) - 3 and 2 < j < len(lons) - 3]


def track_lows(times, lows_by_time):
    """Join each frame's lows into tracks: nearest within 900 km of the last position."""
    tracks = []
    for t, lows in zip(times, lows_by_time):
        used = set()
        for tr in tracks:
            lt, la, lo, _ = tr[-1]
            if (t - lt).total_seconds() > 6 * 3600:
                continue
            best, bd = None, 900
            for n, (a, b, p) in enumerate(lows):
                d = float(gc_dist(la, lo, a, b))
                if n not in used and d < bd:
                    best, bd = n, d
            if best is not None:
                used.add(best)
                tr.append((t, *lows[best]))
        tracks += [[(t, *low)] for n, low in enumerate(lows) if n not in used]
    return [tr for tr in tracks if len(tr) >= 3]


def swell_path(window, la, lo):
    """For sea cells (2-D lat/lon): path length to Saltburn (km), the bearing
    the swell must leave on, and whether it's straight in (True) or through a
    gap north of Scotland (False). NaN where neither works."""
    reach, step = np.array(window['reach']), window['step']
    b_from_s = bearing(ORIGIN[0], ORIGIN[1], la, lo)
    d_direct = gc_dist(ORIGIN[0], ORIGIN[1], la, lo)
    seen = reach[(np.round(b_from_s / step).astype(int)) % len(reach)] >= d_direct - 25
    best_d = np.where(seen, d_direct, np.inf)
    aim = np.where(seen, bearing(la, lo, ORIGIN[0], ORIGIN[1]), np.nan)
    # Out west and north of the Scottish mainland: in through a gap, then on down.
    out_west = (la >= 58.5) & ~seen
    for g in GAPS:
        dg = gc_dist(la, lo, g[0], g[1]) + float(gc_dist(g[0], g[1], ORIGIN[0], ORIGIN[1]))
        better = out_west & (dg < best_d)
        best_d = np.where(better, dg, best_d)
        aim = np.where(better, bearing(la, lo, g[0], g[1]), aim)
    best_d = np.where(np.isfinite(best_d), best_d, np.nan)
    return best_d, aim, seen


def storm_alerts(run, steps, frames, window):
    """Bomb lows in the run whose winds are aimed at Saltburn, with when their
    swell would arrive. frames: per step, dicts of prmsl (Pa), u10, v10 (m/s)
    on a regular lat/lon grid (any resolution; thinned to 1°)."""
    lat_all, lon_all = frames[0]['prmsl'].latitude.values, frames[0]['prmsl'].longitude.values
    k = max(1, int(round(1.0 / abs(float(lat_all[1] - lat_all[0])))))
    lats, lons = lat_all[::k], lon_all[::k]
    LA, LO = np.meshgrid(lats, lons, indexing='ij')
    sea = ~shapely.contains_xy(land(), LO, LA)
    dist, aim, straight = swell_path(window, LA, LO)
    times = [run + dt.timedelta(hours=int(s)) for s in steps]
    P = [f['prmsl'].values[::k, ::k] / 100 for f in frames]
    U = [f['u10'].values[::k, ::k] * KN for f in frames]
    V = [f['v10'].values[::k, ::k] * KN for f in frames]
    tracks = track_lows(times, [find_lows(p, lats, lons) for p in P])
    alerts = []
    for tr in tracks:
        by_t = {t: (la, lo, p) for t, la, lo, p in tr}
        # Deepening over 24 h, in Bergeron units (24 hPa at 60°N; less needed further south).
        best = None
        for t, la, lo, p in tr:
            before = by_t.get(t - dt.timedelta(hours=24))
            if before:
                drop = before[2] - p
                need = 24 * np.sin(np.radians(la)) / np.sin(np.radians(60))
                if best is None or drop / need > best[0]:
                    best = (drop / need, drop, t)
        if not best or best[0] < 1:
            continue
        # Winds near the low (within 1200 km) blowing along a path to Saltburn.
        aimed = []  # (time, km, kn, straight, lat, lon)
        peak_wind = 0
        for t, la, lo, p in tr:
            i = times.index(t)
            near = gc_dist(la, lo, LA, LO) < 1200
            sp = np.hypot(U[i], V[i])
            peak_wind = max(peak_wind, float(np.where(near & sea, sp, 0).max()))
            towards = (np.degrees(np.arctan2(U[i], V[i])) + 360) % 360
            ok = near & sea & np.isfinite(dist) & (sp >= 34) & (np.cos(np.radians(towards - aim)) > np.cos(np.radians(30)))
            for a, b in np.argwhere(ok):
                aimed.append((t, float(dist[a, b]), float(sp[a, b]), bool(straight[a, b]), float(lats[a]), float(lons[b])))
        if len(aimed) < 6:
            continue
        deepest = min(tr, key=lambda e: e[3])
        ms = lambda d: int(d.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
        # First signs: the fastest (20 s) energy from its strongest aimed winds.
        top = max(x[2] for x in aimed)
        strong = [x for x in aimed if x[2] >= max(45, top - 10)]
        first = min(x[0] + dt.timedelta(hours=x[1] / cg_kmh(20)) for x in strong)
        # Pulses: the frame with the strongest aimed wind, and the one with the
        # most aimed wind overall if that's a separate burst (12 h or more apart).
        frames_t = sorted({x[0] for x in aimed})
        energy = {t: sum((x[2] - 30) ** 2 for x in aimed if x[0] == t) for t in frames_t}
        peak = max(frames_t, key=lambda t: max(x[2] for x in aimed if x[0] == t))
        picks = [peak]
        bulk = max(frames_t, key=lambda t: energy[t])
        if abs((bulk - peak).total_seconds()) >= 12 * 3600 and energy[bulk] >= 0.5 * energy[peak]:
            picks.append(bulk)
        pulses = []
        for t in sorted(picks):
            cells = [x for x in aimed if x[0] == t]
            lead = max(cells, key=lambda x: x[2])
            cells = [x for x in cells if x[2] >= max(40, lead[2] - 8)]  # the core of the burst
            pulses.append(dict(
                genAt=ms(t), where=place(lead[4], lead[5]), kn=round(lead[2]),
                arriveFrom=ms(min(t + dt.timedelta(hours=x[1] / cg_kmh(17)) for x in cells)),
                arriveTo=ms(max(t + dt.timedelta(hours=x[1] / cg_kmh(14)) for x in cells)),
                path='straight' if sum(x[3] for x in cells) >= len(cells) / 2 else 'gaps'))
        alerts.append(dict(
            kind='bomb', at=ms(deepest[0]), hPa=round(deepest[3]), lat=round(deepest[1], 1), lon=round(deepest[2], 1),
            where=place(deepest[1], deepest[2]), drop24=round(best[1]), bergeron=round(best[0], 1), deepeningAt=ms(best[2]),
            windKn=round(peak_wind), first=ms(first), pulses=pulses,
            until=max(p['arriveTo'] for p in pulses)))
    alerts.sort(key=lambda a: a['first'])
    return alerts


if __name__ == '__main__':
    # Try it on a saved run's fields.npz (from the charts branch).
    class F:  # a tiny stand-in for the xarray fields
        def __init__(self, v, la, lo):
            self.values, self.latitude, self.longitude = v, type('c', (), {'values': la}), type('c', (), {'values': lo})
    z = np.load(sys.argv[1])
    run = dt.datetime.strptime(str(z['run']), '%Y-%m-%dT%HZ')
    la, lo = z['lat'], z['lon']
    frames = [dict(prmsl=F(z['mslp_dhpa'][i] * 10.0, la, lo), u10=F(z['u10_dms'][i] / 10, la, lo), v10=F(z['v10_dms'][i] / 10, la, lo))
              for i in range(len(z['steps']))]
    w = swell_window()
    print('Open sectors (600 km+):', [(f'{a:.1f}', f'{b:.1f}') for a, b in open_sectors(w)])
    for b in (340, 345, 348, 349, 350, 352, 355, 357, 358, 359, 0, 5, 10, 20, 30, 35, 40, 60, 80, 100, 110, 120):
        print(f'  {b:5.1f} deg: {w["reach"][int(b / w["step"])]} km of sea')
    print(json.dumps(storm_alerts(run, list(z['steps']), frames, w), indent=1))
