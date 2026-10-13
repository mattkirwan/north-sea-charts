"""Where swell can reach Saltburn from, and which storms are sending it.

Two things for the chart job (gfs_charts.py), from the same GFS run:

swell_window() casts rays out from just off Saltburn every half degree, along
great circles (the paths swell takes), until each meets land: Natural Earth's
1:10m coastline, so the Fraserburgh corner and Norway are in the way where
they should be. Islands under ISLAND_KM2 (Shetland, Orkney, the Faroes, Jan
Mayen) are left out: a groundswell arrives spread over a range of
directions, and its shadow behind a thin island hundreds of kilometres away
mostly fills back in. The result is how far open sea runs in each direction:
the swell window. The app shades it, and the travel times only run where
it's open.

storm_alerts() follows every low through the run and flags bombs (pressure
falling at least 24 hPa in 24 hours, scaled for latitude, as forecasters
define it) whose winds are aimed straight down the window at Saltburn, and
works out when that swell would arrive: the first long-period energy and the
main pulses, from the deep-water group speed g*T/4pi. Swell doesn't bend far
in deep water, so winds aimed well away (at Norway, say) count for nothing
here; the alert just notes where the storm's strongest winds were, if they
missed.

Three bends are allowed for, and come out smaller:
- North-west, round the Aberdeenshire corner: up to NW_FAN degrees, which
  reaches the sea off east Iceland and the Faroes (a groundswell's spread of
  directions, and diffraction round the corner).
- Through the gap between Orkney and Shetland (GAP), from GAP_FAN: the
  Atlantic south of Iceland. Swell from storms there heading for Norway
  spills through the gap and turns down the North Sea to us from the north,
  as NOAA's wave model had it on 15 Oct 2026 and the buoys saw on 16 Mar 2026
  (18-22 s, the rarest and best swell we get).
- South-east, along the Yorkshire coast: SE swell from the southern North
  Sea bends in round the headlands in the shallows. Rays ignore land in the
  first SE_SHORE_KM (out past Flamborough Head) for up to SE_FAN degrees
  past the window's edge.

swell_forecast() is our own swell forecast for Saltburn from the run's winds:
for every path swell can take in (the window, and the two bends), it finds
stretches of wind blowing along the path towards us, grows waves from the
wind speed, the stretch's length (fetch) and how long it has blown (the
standard deep-water growth curves; none over close-packed sea ice), and
sends that swell on to Saltburn at the group speed for its period, smaller
with distance (fitted to Bretschneider's swell decay curves). It starts
from the last few days' analyses as well as the run itself, so swell
already on its way when the run starts is counted. Hour by hour, the
biggest arriving swell is turned into a breaking size at Saltburn (Komar and
Gaughan, less at an angle to the beach), and each rise to knee-high or more
(a peak standing out from the hours around it) is a swell event. Simple on purpose: a starting point to check against
the buoys and what we see, and tune.

Not yet allowed for: the sea bed. Crossing the North Sea's shallows (EMODnet
has its depths in detail), swell slows, bends and loses height to the bottom,
more so the longer its period. The plan is to let the reports from the beach
show how far out each direction and period comes, then bring in the depths
to explain it.

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
from scipy.ndimage import gaussian_filter, maximum_filter1d, minimum_filter
from scipy.signal import find_peaks
from shapely.geometry import box, shape
from shapely.ops import unary_union

SALTBURN = (54.5838, -0.9724)
ORIGIN = (54.605, -0.955)     # rays start a little off the pier, in the sea
LAND_URL = 'https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip'
STEP_DEG, MAX_KM, RAY_KM = 0.5, 3500, 4
ISLAND_KM2 = 3000  # islands smaller than this don't block the window
NW_FAN, SE_FAN, SE_SHORE_KM = 30, 45, 85
SE_ARRIVE = 105    # the most side-on (degrees) swell bending in from the south-east arrives
GAP = (59.5, -1.9)                   # sea between Orkney and Fair Isle
GAP_FAN = (265, 340)                 # bearings from the gap out to the Atlantic south of Iceland
GAP_SHARE = 0.35                     # less gets through and round than at the other bends
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
            if not g.intersects(area):
                continue
            for poly in getattr(g, 'geoms', [g]):
                c = poly.centroid
                km2 = poly.area * 111.2 ** 2 * np.cos(np.radians(c.y))
                if km2 >= ISLAND_KM2:
                    parts.append(poly.buffer(0).intersection(area))
        _land = unary_union(parts)
        shapely.prepare(_land)
    return _land


def rays(lat, lon, max_km, skip_km=0):
    """km of open sea from (lat, lon) along each bearing, to the first land
    (ignoring any in the first skip_km)."""
    bearings = np.arange(0, 360, STEP_DEG)
    dists = np.arange(RAY_KM, max_km + RAY_KM, RAY_KM)
    B, D = np.meshgrid(bearings, dists, indexing='ij')
    la, lo = destination(lat, lon, B, D)
    hit = shapely.contains_xy(land(), lo, la) & (D > skip_km)
    return np.where(hit.any(axis=1), dists[np.argmax(hit, axis=1)] - RAY_KM, max_km).astype(float)


def swell_window():
    """Open sea from just off Saltburn: km to the first land along each
    bearing (0, 0.5, ... 359.5 degrees), up to MAX_KM. And the two bends: for
    each, the point the swell bends round, its distance on to Saltburn, and
    the sea that can reach it in the fan (km per bearing from that point, 0
    outside the fan)."""
    reach = rays(*ORIGIN, MAX_KM)
    n, step = len(reach), STEP_DEG
    bearings = np.arange(0, 360, step)
    bends = []
    # North-west: the last bearing (looking anticlockwise from north) that hits
    # the Scottish coast before the window opens out.
    edge = next(i for i in range(int(340 / step), int(360 / step)) if reach[i] < 600 and reach[(i + 1) % n] >= 1000)
    # The swell bends round just past the headland: on the first open bearing,
    # a little beyond the land that stops the one before.
    corner = destination(ORIGIN[0], ORIGIN[1], (edge + 1) * step, reach[edge] + 20)
    out = float(bearing(corner[0], corner[1], *destination(ORIGIN[0], ORIGIN[1], (edge + 1) * step, reach[edge] + 400)))
    fan = ((out - bearings + 360) % 360 <= NW_FAN)
    r = rays(float(corner[0]), float(corner[1]), MAX_KM)
    bends.append(dict(name='round the Aberdeenshire coast', lat=round(float(corner[0]), 4), lon=round(float(corner[1]), 4),
                      km=int(gc_dist(corner[0], corner[1], ORIGIN[0], ORIGIN[1])), start=0, reach=[int(v) for v in np.where(fan, r, 0)]))
    # South-east: past the last open bearing before the Yorkshire coast closes it.
    edge = next(i for i in range(int(90 / step), int(150 / step)) if reach[i] >= 300 and reach[i + 1] < 50)
    fan = ((bearings - edge * step + 360) % 360 <= SE_FAN) & ((bearings - edge * step + 360) % 360 > 0)
    r = rays(*ORIGIN, MAX_KM, SE_SHORE_KM)
    r = np.where(r > SE_SHORE_KM, r, 0)
    bends.append(dict(name='along the Yorkshire coast', lat=ORIGIN[0], lon=ORIGIN[1], km=0, start=SE_SHORE_KM,
                      reach=[int(v) for v in np.where(fan, r, 0)]))
    # North: through the gap between Orkney and Shetland, which Saltburn sees
    # straight up the North Sea.
    fan = (bearings >= GAP_FAN[0]) & (bearings <= GAP_FAN[1])
    r = rays(*GAP, MAX_KM)
    bends.append(dict(name='through the gap between Orkney and Shetland', lat=GAP[0], lon=GAP[1],
                      km=int(gc_dist(GAP[0], GAP[1], ORIGIN[0], ORIGIN[1])), start=0, share=GAP_SHARE,
                      reach=[int(v) for v in np.where(fan, r, 0)]))
    return dict(origin=list(ORIGIN), step=step, maxKm=MAX_KM, reach=[int(v) for v in reach], bends=bends)


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
    the swell must leave on, and whether Saltburn is in sight down the window.
    NaN where it isn't."""
    reach, step = np.array(window['reach']), window['step']
    b_from_s = bearing(ORIGIN[0], ORIGIN[1], la, lo)
    d_direct = gc_dist(ORIGIN[0], ORIGIN[1], la, lo)
    idx = lambda b: (np.round(b / step).astype(int)) % len(reach)
    seen = reach[idx(b_from_s)] >= d_direct - 25
    best_d = np.where(seen, d_direct, np.inf)
    aim = np.where(seen, bearing(la, lo, ORIGIN[0], ORIGIN[1]), np.nan)
    # Or bending in at one of the window's edges.
    for g in window.get('bends', []):
        gr = np.array(g['reach'])
        d_b = gc_dist(g['lat'], g['lon'], la, lo)
        via = ~seen & (gr[idx(bearing(g['lat'], g['lon'], la, lo))] >= np.maximum(d_b - 25, 1))
        dv = d_b + g['km']
        better = via & (dv < best_d)
        best_d = np.where(better, dv, best_d)
        aim = np.where(better, bearing(la, lo, g['lat'], g['lon']), aim)
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
        peak_wind, peak_at = 0, None
        for t, la, lo, p in tr:
            i = times.index(t)
            near = gc_dist(la, lo, LA, LO) < 1200
            sp = np.hypot(U[i], V[i])
            m = np.where(near & sea, sp, 0)
            if m.max() > peak_wind:
                a, b = np.unravel_index(np.argmax(m), m.shape)
                peak_wind, peak_at = float(m.max()), (t, float(lats[a]), float(lons[b]))
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
        strong = [x for x in aimed if x[2] >= max(min(45, top), top - 10)]  # always includes the strongest
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
            cells = [x for x in cells if x[2] >= max(min(40, lead[2]), lead[2] - 8)]  # the core of the burst
            pulses.append(dict(
                genAt=ms(t), where=place(lead[4], lead[5]), kn=round(lead[2]),
                arriveFrom=ms(min(t + dt.timedelta(hours=x[1] / cg_kmh(17)) for x in cells)),
                arriveTo=ms(max(t + dt.timedelta(hours=x[1] / cg_kmh(14)) for x in cells)),
                path='straight' if sum(x[3] for x in cells) >= len(cells) / 2 else 'bend'))
        alerts.append(dict(
            kind='bomb', at=ms(deepest[0]), hPa=round(deepest[3]), lat=round(deepest[1], 1), lon=round(deepest[2], 1),
            where=place(deepest[1], deepest[2]), drop24=round(best[1]), bergeron=round(best[0], 1), deepeningAt=ms(best[2]),
            windKn=round(peak_wind), first=ms(first), pulses=pulses,
            # Its strongest winds, if they weren't aimed down our window (most of that swell goes elsewhere).
            missed=None if max(x[2] for x in aimed) >= peak_wind - 5 else dict(at=ms(peak_at[0]), kn=round(peak_wind), where=place(peak_at[1], peak_at[2])),
            until=max(p['arriveTo'] for p in pulses)))
    alerts.sort(key=lambda a: a['first'])
    return alerts


G = 9.81
BEACH_FACES = 20            # Saltburn's beach faces NNE: the pier points 20° true (its mapped outline, OSM way 624089530)
WIND_MIN = 8.0              # m/s along the path (about 16 kn) to grow swell
DECAY = 0.7                 # swell height falls as (fetch / (fetch + distance)) ** DECAY
ICE_TENTHS = 4              # no waves grow over ice this close packed
RAY_STEP_KM, RAY_EVERY = 20, 2.0
EVENT_FT, EVENT_HOURS = 1.5, 3   # knee-high or more, for at least 3 hours
EVENT_APART, EVENT_RISE = 18, 1.0  # peaks at least 18 h apart, standing 1 ft above the dip between


def grow(u, fetch_m, hours):
    """Significant height (m) and peak period (s) from the 10 m wind u (m/s)
    over a fetch (m) for a duration (h): the JONSWAP deep-water curves, fetch-
    or duration-limited, capped at a fully developed sea."""
    x = G * fetch_m / u ** 2
    x = min(x, (G * hours * 3600 / (68.8 * u)) ** 1.5)    # or as far as it's had time to grow
    h = min(1.6e-3 * np.sqrt(x), 0.2433) * u ** 2 / G
    t = min(0.2857 * x ** (1 / 3), 8.134) * u / G
    return h, t


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


def ice_from_shp(path):
    """The close-packed ice (ICE_TENTHS or more) in an ice chart shapefile."""
    r = shapefile.Reader(path)
    names = [f[0] for f in r.fields[1:]]
    out = []
    for sr in r.iterShapeRecords():
        t = ice_tenths(dict(zip(names, sr.record)).get('CT'))
        if t is not None and t >= ICE_TENTHS and sr.shape.points:
            out.append(shape(sr.shape.__geo_interface__).buffer(0))
    return unary_union(out) if out else None


def break_ft(h0, t, from_deg):
    """Breaking size at Saltburn (ft) from offshore swell height (m), period
    (s) and the direction it comes from: Komar and Gaughan, times the square
    root of the cosine of its angle to the beach."""
    off = abs(((from_deg - BEACH_FACES) % 360 + 540) % 360 - 180)
    if off >= 90 or h0 <= 0:
        return 0.0
    hb = 0.39 * G ** 0.2 * (t * h0 * h0) ** 0.4
    return hb * np.sqrt(np.cos(np.radians(off))) * 3.281


def _paths(window):
    """The rays swell comes in along: from Saltburn out down the window, and
    out from each bend (with the distance on to Saltburn, a share for the
    swell lost in the bend, and the way it finally arrives from)."""
    reach, step = np.array(window['reach']), window['step']
    out = []
    for b in np.arange(0, 360, RAY_EVERY):
        r = reach[int(round(b / step)) % len(reach)]
        if r >= 60:
            out.append(dict(lat=ORIGIN[0], lon=ORIGIN[1], b=b, start=0, end=min(r, MAX_KM), km=0, share=1.0, arrive=b))
    for g in window.get('bends', []):
        gr = np.array(g['reach'])
        # Swell bending round the north-west corner arrives from the corner;
        # swell bending in along the coast from the south-east has turned to
        # come in no squarer than ESE (it would otherwise run past the beach).
        arrive = float(bearing(ORIGIN[0], ORIGIN[1], g['lat'], g['lon'])) if g['km'] else None
        for b in np.arange(0, 360, RAY_EVERY):
            r = gr[int(round(b / step)) % len(gr)]
            if r > max(g['start'], 60):
                out.append(dict(lat=g['lat'], lon=g['lon'], b=b, start=g['start'], end=min(r, MAX_KM - g['km']), km=g['km'],
                                share=g.get('share', 0.5), arrive=arrive if arrive is not None else min(b, SE_ARRIVE)))
    return out


def winds_from_npz(z, every=1):
    """The 10 m winds from a fields.npz (or analyses.npz), as swell_forecast
    takes them: every'th grid point, in m/s."""
    if 'times' in z:
        times = [dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=int(t)) for t in z['times']]
    else:
        run = dt.datetime.strptime(str(z['run']), '%Y-%m-%dT%HZ')
        times = [run + dt.timedelta(hours=int(h)) for h in z['steps']]
    return dict(lat=z['lat'][::every], lon=z['lon'][::every], times=times,
                u=z['u10_dms'][:, ::every, ::every] / 10.0, v=z['v10_dms'][:, ::every, ::every] / 10.0)


def join_winds(past, now):
    """The past analyses (before the run, on the same grid), then the run."""
    if not past or past['u'].shape[1:] != now['u'].shape[1:]:
        return now
    keep = [k for k, t in enumerate(past['times']) if t < now['times'][0]]
    if not keep:
        return now
    return dict(lat=now['lat'], lon=now['lon'], times=[past['times'][k] for k in keep] + list(now['times']),
                u=np.concatenate([past['u'][keep], now['u']]), v=np.concatenate([past['v'][keep], now['v']]))


def swell_forecast(run, winds, window, ice=None, days=8):
    """Hourly swell forecast for Saltburn from the run's start, and its swell
    events. winds: the 10 m winds (winds_from_npz), from the past few days'
    analyses on through the run; ice: the close-packed sea ice (a shapely
    geometry), if known."""
    run = run.replace(tzinfo=None)  # all times here are plain UTC
    lat_all, lon_all, times = winds['lat'], winds['lon'], winds['times']
    dlat, dlon = float(lat_all[1] - lat_all[0]), float(lon_all[1] - lon_all[0])
    paths = _paths(window)
    pts = []
    for pth in paths:
        d = np.arange(pth['start'] + RAY_STEP_KM / 2, pth['end'], RAY_STEP_KM)
        la, lo = destination(pth['lat'], pth['lon'], pth['b'], d)
        toward = bearing(la, lo, pth['lat'], pth['lon'])          # the way swell must travel to get in
        i = np.clip(np.round((la - lat_all[0]) / dlat).astype(int), 0, len(lat_all) - 1)
        j = np.clip(np.round((lo - lon_all[0]) / dlon).astype(int), 0, len(lon_all) - 1)
        open_sea = ~shapely.contains_xy(ice, lo, la) if ice is not None else np.ones(len(d), bool)
        pts.append(dict(d=d, la=la, lo=lo, toward=toward, i=i, j=j, sea=open_sea, hours=np.zeros(len(d))))
    packets = []  # (arrival, height m, period s, from deg, share, src lat, src lon, made at)
    for k, t in enumerate(times):
        u, v = winds['u'][k], winds['v'][k]
        gap = 6 if k == 0 else min((t - times[k - 1]).total_seconds() / 3600, 12)  # a missing analysis: don't count the gap as wind
        for pth, pt in zip(paths, pts):
            uu, vv = u[pt['i'], pt['j']], v[pt['i'], pt['j']]
            sp = np.hypot(uu, vv)
            ang = np.abs(((np.degrees(np.arctan2(uu, vv)) - pt['toward']) % 360 + 540) % 360 - 180)
            along = np.where(ang < 45, sp * np.cos(np.radians(ang)), 0)
            windy = (along >= WIND_MIN) & pt['sea']
            pt['hours'] = np.where(windy, pt['hours'] + gap, 0)
            if not windy.any():
                continue
            # Each stretch of wind along the path, from its far end in to its near end.
            edges = np.flatnonzero(np.diff(np.concatenate(([0], windy.astype(int), [0]))))
            for a, b in zip(edges[::2], edges[1::2]):
                fetch = (pt['d'][b - 1] - pt['d'][a] + RAY_STEP_KM) * 1000
                h, per = grow(float(along[a:b].mean()), fetch, float(np.median(pt['hours'][a:b])))
                near = pt['d'][a] + pth['km']                          # km on to Saltburn from the stretch's near end
                h_arr = h * (fetch / (fetch + near * 1000)) ** DECAY * pth['share']
                if h_arr < 0.05:
                    continue
                arrive = t + dt.timedelta(hours=near / cg_kmh(per))
                m = (a + b) // 2
                packets.append((arrive, h_arr, per, pth['arrive'], float(pt['la'][m]), float(pt['lo'][m]), t))
    # Hour by hour: the biggest swell arriving (each frame's swell spread over its 6 hours).
    start = run.replace(minute=0, second=0, microsecond=0)
    hours = [start + dt.timedelta(hours=h) for h in range(24 * days)]
    series = []
    for hr in hours:
        best = None
        for pk in packets:
            if abs((pk[0] - hr).total_seconds()) <= 3 * 3600:
                ft = break_ft(pk[1], pk[2], pk[3])
                if best is None or ft > best[0]:
                    best = (ft, pk)
        if best:
            ft, pk = best
            series.append(dict(t=hr, ft=round(ft, 2), h=round(pk[1], 2), p=round(pk[2], 1), d=round(pk[3]), src=(pk[4], pk[5]), made=pk[6]))
        else:
            series.append(dict(t=hr, ft=0.0, h=0.0, p=None, d=None, src=None, made=None))
    return series, find_events(series)


def find_events(series):
    """Swell events: each peak, out to where it falls under EVENT_FT (or under
    40% of the peak, or the dip before the next one). The hourly sizes are
    smoothed a little first: neighbouring paths take turns being biggest."""
    ft = maximum_filter1d(np.array([r['ft'] for r in series]), 3)
    peaks, _ = find_peaks(np.concatenate(([0], ft, [0])), height=EVENT_FT, distance=EVENT_APART, prominence=EVENT_RISE)
    peaks = list(peaks - 1)
    events = []
    for n, k in enumerate(peaks):
        floor = max(EVENT_FT, 0.4 * ft[k])
        lo = peaks[n - 1] + int(np.argmin(ft[peaks[n - 1]:k])) if n else 0
        hi = k + int(np.argmin(ft[k:peaks[n + 1] + 1])) if n + 1 < len(peaks) else len(ft) - 1
        a, b = k, k
        while a > lo and ft[a - 1] >= floor:
            a -= 1
        while b < hi and ft[b + 1] >= floor:
            b += 1
        if b - a + 1 < EVENT_HOURS:
            continue
        pk = max(series[a:b + 1], key=lambda r: r['ft'])
        events.append(dict(start=series[a]['t'], end=series[b]['t'], peak=pk['t'], ft=pk['ft'], h=pk['h'], p=pk['p'], d=pk['d'],
                           where=place(*pk['src']) if pk['src'] else None, made=pk['made']))
    return events


def forecast_json(run, series, events, model='v0'):
    """hourly: [time, size ft, height m, period s, from deg], and for the
    NOAA model, each swell reaching Saltburn: [[m, s, from, ft], ...]."""
    ms = lambda d: int(d.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    return dict(
        run=ms(run), model=model,
        hourly=[[ms(r['t']), r['ft'], r['h'], r['p'], r['d']] + ([r['swells']] if 'swells' in r else []) for r in series],
        events=[dict(start=ms(e['start']), end=ms(e['end']), peak=ms(e['peak']), ft=e['ft'], h=e['h'], p=e['p'], d=e['d'],
                     where=e['where'], made=ms(e['made'])) for e in events])


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
    print('Open sectors (1000 km+):', [(f'{a:.1f}', f'{b:.1f}') for a, b in open_sectors(w, 1000)])
    for g in w['bends']:
        on = [i * w['step'] for i, v in enumerate(g['reach']) if v > 0]
        print(f"  bend {g['name']} at {g['lat']},{g['lon']} ({g['km']} km on): {len(on)} bearings, {min(on) if on else '-'}..{max(on) if on else '-'}, reach up to {max(g['reach'])} km")
    for b in (340, 345, 348, 349, 350, 352, 355, 357, 358, 359, 0, 5, 10, 20, 30, 35, 40, 60, 80, 100, 110, 120):
        print(f'  {b:5.1f} deg: {w["reach"][int(b / w["step"])]} km of sea')
    print(json.dumps(storm_alerts(run, list(z['steps']), frames, w), indent=1))
    ice = ice_from_shp(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != '-' else None
    winds = winds_from_npz(z, 2)
    if len(sys.argv) > 3:  # an earlier run's fields.npz, for its analysis... or an analyses.npz
        winds = join_winds(winds_from_npz(np.load(sys.argv[3]), 2), winds)
    series, events = swell_forecast(run, winds, w, ice)
    print('Forecast events:')
    for e in events:
        print(f"  {e['start']:%a %d %H}z - {e['end']:%a %d %H}z, peak {e['peak']:%a %d %H}z {e['ft']:.1f} ft ({e['h']:.2f} m {e['p']:.0f} s from {e['d']}) from {e['where']}")
    for r in series[::6]:
        print(f"    {r['t']:%a %d %H}z {r['ft']:4.1f} ft  {r['h']:.2f} m {r['p'] or 0:4.1f} s {r['d'] if r['d'] is not None else '-'}")
