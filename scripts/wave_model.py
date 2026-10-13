"""Our swell forecast for Saltburn from NOAA's wave model.

NOAA's GFS-Wave (WAVEWATCH III) runs with each GFS run and publishes, for a
few hundred buoys and platforms, every separate swell it sees there, hour by
hour: height, peak period and direction. The nearest to Saltburn on the swell's
way in is WMO 62026, 150 km north-east (55.3N 1.1E). We take each of its swells
that can reach Saltburn's beach and turn it into breaking size there
(to_saltburn: the buoy rule, swell_sources.break_ft, scaled by period); swells
running together add as energy. So the offshore part is NOAA's and the last 150 km is ours: the
part your reports will tune, by period and direction.

The bulletins (gfswave.<id>.bull on NOAA's open data bucket) are kept for every
run since March 2021, so any past forecast can be made again.
"""
import datetime as dt
import sys
import time
import urllib.request

import numpy as np

import swell_sources
from gfs_latest import bulletin_url
from swell_sources import break_ft

POINT = '62026'      # 150 km NE of Saltburn
MIN_HS = 0.05        # smaller swells (m) aren't counted
# The last 150 km: breaking size by the buoy rule, times GAIN * (period / 10 s)
# ** PERIOD_POW, at most MAX_GAIN. Provisional, from the first two reports (12
# and 13 Oct, 8-9 s swell breaking at a third of the rule) and long experience
# that a small 20 s swell breaks at 4-6 ft: short-period swell loses height on
# the way in, long-period swell bends in and steepens. Reports refit these.
GAIN = 0.43
PERIOD_POW = 2.2
MAX_GAIN = 3.0


def to_saltburn(hs, tp, from_deg):
    """Breaking size at Saltburn (ft) of a swell 150 km out."""
    return float(break_ft(hs, tp, from_deg)) * min(MAX_GAIN, GAIN * (tp / 10) ** PERIOD_POW)


def fetch_bulletin(run, point=POINT, wait_min=0):
    """The run's bulletin for a point, waiting up to wait_min minutes for it
    (they come out about 5½ hours after the run, just after the GFS)."""
    end = time.time() + wait_min * 60
    while True:
        try:
            with urllib.request.urlopen(bulletin_url(run, point), timeout=60) as r:
                return r.read().decode()
        except Exception as e:
            if time.time() >= end:
                raise RuntimeError(f'No wave model bulletin for {run:%Y-%m-%d %H}z at {point}: {e}')
            time.sleep(60)


def parse_bulletin(text, run, days=8):
    """[(time, [(m, s, from deg, local wind), ...]), ...] hourly from the run.
    The bulletin's directions are where each swell is heading."""
    run = run.replace(tzinfo=None)
    rows, year, month, last = [], run.year, run.month, run.day
    for line in text.splitlines():
        cells = line.split('|')
        if len(cells) < 5:
            continue
        dh = cells[1].split()
        if len(dh) != 2 or not all(x.isdigit() for x in dh):
            continue
        day, hour = int(dh[0]), int(dh[1])
        if day < last:  # into the next month
            month, year = (1, year + 1) if month == 12 else (month + 1, year)
        last = day
        t = dt.datetime(year, month, day, hour)
        if t > run + dt.timedelta(days=days):
            break
        swells = []
        for c in cells[3:]:
            a = c.replace('*', '').split()
            if len(a) == 3:
                hs, tp, to = (float(x) for x in a)
                if hs >= MIN_HS:
                    swells.append((hs, tp, (to + 180) % 360, '*' in c))
        rows.append((t, swells))
    if not rows:
        raise ValueError('Not a wave model bulletin')
    return rows


def ww3_forecast(run, rows):
    """Hourly forecast and swell events for Saltburn from the bulletin rows."""
    series = []
    for t, swells in rows:
        reach = [(hs, tp, fr, to_saltburn(hs, tp, fr)) for hs, tp, fr, _ in swells]
        reach = [r for r in reach if r[3] > 0]
        if not reach:
            series.append(dict(t=t, ft=0.0, h=0.0, p=None, d=None, src=None, made=None, swells=[]))
            continue
        top = max(reach, key=lambda r: r[3])
        series.append(dict(t=t, ft=round(float(np.sqrt(sum(r[3] ** 2 for r in reach))), 2),
                           h=round(float(np.sqrt(sum(r[0] ** 2 for r in reach))), 2), p=top[1], d=round(top[2]),
                           src=None, made=run.replace(tzinfo=None),
                           swells=[[r[0], r[1], round(r[2]), round(r[3], 2)] for r in sorted(reach, key=lambda r: -r[3])]))
    events = swell_sources.find_events(series)
    for e in events:
        e['where'] = 'NOAA wave model'
    return series, events


if __name__ == '__main__':
    # forecast RUN OUT.json: write that run's forecast (RUN as 2026-10-13-00z).
    # show RUN: print it.
    cmd = sys.argv[1]
    run = dt.datetime.strptime(sys.argv[2], '%Y-%m-%d-%Hz')
    series, events = ww3_forecast(run, parse_bulletin(fetch_bulletin(run), run))
    if cmd == 'forecast':
        import json
        with open(sys.argv[3], 'w') as fh:
            json.dump(swell_sources.forecast_json(run, series, events, model='ww3'), fh, separators=(',', ':'))
    for r in series[::6]:
        print(f"{r['t']:%a %d %H}z {r['ft']:5.1f} ft  " + '  '.join(f'{a} m {b} s {c}° {d} ft' for a, b, c, d in r['swells']))
    for e in events:
        print(f"event {e['start']:%a %H}z-{e['end']:%a %H}z peak {e['peak']:%a %H}z {e['ft']} ft ({e['h']} m {e['p']} s from {e['d']})")
