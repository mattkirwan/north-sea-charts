"""Keep the record our swell predictions are judged against.

Run by the chart job after each new GFS run is published, on a checkout of
the `history` branch (which only ever grows):

  python scripts/history.py CHARTS_DIR WAVES_JSON HISTORY_DIR

- forecasts/<run>.json: every run's swell forecast (forecast.json), as made.
- buoys/<code>.json: the readings from each coastal buoy, merged run after
  run from the last 24 hours the wave collector holds, so nothing is lost.
- held.json: each swell, held as first predicted. The first run to see a swell
  coming (at least HOLD_AHEAD hours ahead) fixes its prediction, which never
  changes. Each later run adds its own view of the same swell (its peak
  within MATCH_HOURS and its direction within MATCH_DEG of the last view), or
  notes the swell has gone from that run. Once it has been and gone, the
  biggest Whitby reading over its time is added: what actually came.
"""
import datetime as dt
import json
import os
import sys

from swell_sources import break_ft

HOLD_AHEAD = 24     # h: a swell is only held if it was seen this far ahead
MATCH_HOURS = 18    # a later run's swell is the same one if it peaks within this...
MATCH_DEG = 45      # ...and comes from within this of the last view
WATCH = 'Whitby'    # the buoy that says what came
H = 3600 * 1000


def load(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save(path, data):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w') as fh:
        json.dump(data, fh, separators=(',', ':'))


def off(a, b):
    return abs((a - b + 180) % 360 - 180)


def label(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime('%Y-%m-%d-%Hz')


def keep_buoys(waves, out):
    """Merge each buoy's last 24 hours into its file. Returns {name: code}."""
    names = {}
    for st in waves.get('stations', []):
        rows = st.get('hist') or []
        if not rows:
            continue
        names[st['name']] = st['code']
        path = os.path.join(out, 'buoys', f"{st['code']}.json")
        b = load(path, dict(name=st['name'], code=st['code'], lat=st['lat'], lon=st['lon'], rows=[]))
        have = {r[0]: r for r in b['rows']}
        for r in rows:
            have[r[0]] = r
        b['rows'] = [have[k] for k in sorted(have)]
        save(path, b)
    return names


def view_of(run, e):
    return dict(run=run, peak=e['peak'], start=e['start'], end=e['end'], ft=e['ft'], h=e['h'], p=e['p'], d=e['d'], where=e['where'])


def hourly_around(fc, start, end):
    return [[r[0], r[1]] for r in fc['hourly'] if start - 12 * H <= r[0] <= end + 12 * H]


def observed(sw, out, names):
    """The biggest reading at the watched buoy while the swell was due."""
    code = names.get(WATCH)
    seen = [v for v in sw['views'] if not v.get('gone')]
    a = min(v['start'] for v in seen) - 6 * H
    b = max(v['end'] for v in seen) + 12 * H
    rows = load(os.path.join(out, 'buoys', f'{code}.json'), {}).get('rows', []) if code else []
    rows = [r for r in rows if a <= r[0] <= b and r[1] is not None]
    if not rows or rows[-1][0] < b - 3 * H:
        return None
    top = max(rows, key=lambda r: r[1])
    ft = break_ft(top[1], top[2] or 0, top[3]) if top[2] and top[3] is not None else None
    hourly = [r for i, r in enumerate(rows) if i % 2 == 0 or r is top]
    return dict(buoy=WATCH, at=top[0], h=top[1], p=top[2], d=top[3], ft=round(float(ft), 1) if ft is not None else None, rows=hourly)


def main():
    charts, waves_path, out = sys.argv[1:4]
    fc = load(os.path.join(charts, 'forecast.json'), None)
    if not fc:
        print('No forecast this run; nothing to keep.')
        return
    run = fc['run']
    now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    save(os.path.join(out, 'forecasts', f'{label(run)}.json'), fc)
    names = keep_buoys(load(waves_path, {}), out)

    held = load(os.path.join(out, 'held.json'), dict(swells=[]))
    if any(v['run'] == run for sw in held['swells'] for v in sw['views']):
        print(f'{label(run)} already in held.json')
        return
    held['model'] = fc.get('model')
    events = list(fc['events'])
    for sw in held['swells']:
        if sw['status'] != 'coming':
            continue
        last = next(v for v in reversed(sw['views']) if not v.get('gone'))
        near = [e for e in events if abs(e['peak'] - last['peak']) <= MATCH_HOURS * H and off(e['d'], last['d']) <= MATCH_DEG]
        if near:
            e = min(near, key=lambda e: abs(e['peak'] - last['peak']))
            events.remove(e)
            sw['views'].append(view_of(run, e))
            sw['latestHourly'] = hourly_around(fc, e['start'], e['end'])
        elif last['end'] > run:
            sw['views'].append(dict(run=run, gone=True))
    n = 0
    for e in events:
        if e['peak'] < run + HOLD_AHEAD * H:
            continue  # too close to call: swell already on its way isn't in the run
        n += 1
        v = view_of(run, e)
        hourly = hourly_around(fc, e['start'], e['end'])
        held['swells'].append(dict(id=f'{label(run)}-{n}', held=v, views=[v], status='coming',
                                   heldHourly=hourly, latestHourly=hourly, observed=None))
    # Swells that have been and gone: what came.
    for sw in held['swells']:
        seen = [v for v in sw['views'] if not v.get('gone')]
        end = max(v['end'] for v in seen)
        if sw['status'] == 'coming' and end + 12 * H < now:
            sw['status'] = 'passed'
        if sw['status'] == 'passed' and not sw.get('observed') and now < end + 4 * 24 * H:
            sw['observed'] = observed(sw, out, names)
    held['updated'] = now
    save(os.path.join(out, 'held.json'), held)
    coming = [sw for sw in held['swells'] if sw['status'] == 'coming']
    print(f'{label(run)}: {n} new swells held; {len(coming)} coming, {len(held["swells"])} in all')
    for sw in coming:
        h, last = sw['held'], sw['views'][-1]
        now_s = 'gone from this run' if last.get('gone') else f"now {last['ft']} ft, peak {label(last['peak'])}"
        print(f"  {sw['id']}: held {h['ft']} ft, peak {label(h['peak'])} from {h['d']}; {now_s}")


if __name__ == '__main__':
    main()
