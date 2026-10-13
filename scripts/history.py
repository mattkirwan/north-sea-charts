"""Keep the record our swell predictions are judged against.

Run by the forecast job (.github/workflows/forecast.yml) after each run of
NOAA's wave model, on a checkout of the `history` branch (which only ever
grows):

  python scripts/history.py FORECAST_JSON V0_JSON WAVES_JSON HISTORY_DIR

FORECAST_JSON is the run's forecast from NOAA's wave model (wave_model.py);
V0_JSON our own from the winds (the chart job's forecast.json), kept beside it
for comparison when it's from the same run.

Every run forecasts every hour of the next 8 days, so every hour gets ~32
predictions, made from 8 days ahead down to the hour itself. Those, the buoy
readings and the reports from the beach (on the `reports` branch) show how
good the forecast is, and how that changes with how far ahead it was made.

- forecasts/<run>.json: every run's swell forecast, as made.
- forecasts-v0/<run>.json: our own forecast from the winds for the same run.
- days/<date>.json: every prediction made for each hour of that day (UTC), from
  every run: rows of [hour, run, ft, m, s, from]. The app reads these to show
  what was predicted for the time of a report.
- buoys/<code>.json: the readings from each coastal buoy, merged run after
  run from the last 24 hours the wave collector holds, so nothing is lost.
- verify.json: over the last VERIFY_DAYS, the predictions against the Whitby
  buoy, by how many days ahead they were made: how far out on average (bias)
  and typically (mean absolute error), in height offshore and breaking size.
"""
import datetime as dt
import json
import os
import sys

from swell_sources import break_ft

WATCH = 'Whitby'     # the buoy the forecast is checked against
VERIFY_DAYS = 30
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


def utc(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)


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


def keep_hours(fc, out):
    """File each of the run's hourly predictions under the day it's for,
    replacing any filed before for the same run. Returns the number filed."""
    run, by_day = fc['run'], {}
    for t, ft, h, p, d, *_ in fc['hourly']:
        if t >= run:
            by_day.setdefault(utc(t).strftime('%Y-%m-%d'), []).append([t, run, ft, h, p, d])
    added = 0
    for day, rows in by_day.items():
        path = os.path.join(out, 'days', f'{day}.json')
        f = load(path, dict(date=day, rows=[]))
        f['rows'] = sorted([r for r in f['rows'] if r[1] != run] + rows, key=lambda r: (r[0], r[1]))
        save(path, f)
        added += len(rows)
    return added


def verify(out, names, now):
    """The predictions for the last VERIFY_DAYS against the watched buoy, by
    days ahead (0: made less than a day before)."""
    code = names.get(WATCH)
    rows = load(os.path.join(out, 'buoys', f'{code}.json'), {}).get('rows', []) if code else []
    seen = {}
    for r in rows:  # the reading nearest each hour (within 20 minutes)
        if r[1] is None:
            continue
        hr = round(r[0] / H) * H
        if abs(r[0] - hr) <= 20 * 60 * 1000 and (hr not in seen or abs(r[0] - hr) < abs(seen[hr][0] - hr)):
            seen[hr] = r
    stats = {}
    for k in range(VERIFY_DAYS + 1):
        day = utc(now - k * 24 * H).strftime('%Y-%m-%d')
        for t, run, ft, h, p, d in load(os.path.join(out, 'days', f'{day}.json'), {}).get('rows', []):
            b = seen.get(t)
            if not b or t > now or t < now - VERIFY_DAYS * 24 * H:
                continue
            s = stats.setdefault(int((t - run) // (24 * H)), dict(n=0, dh=0.0, ah=0.0, nft=0, dft=0.0, aft=0.0))
            s['n'] += 1
            s['dh'] += h - b[1]
            s['ah'] += abs(h - b[1])
            if b[2] and b[3] is not None:
                e = ft - float(break_ft(b[1], b[2], b[3]))
                s['nft'] += 1
                s['dft'] += e
                s['aft'] += abs(e)
    lead = []
    for k in sorted(stats):
        s = stats[k]
        lead.append(dict(days=k, n=s['n'], biasM=round(s['dh'] / s['n'], 2), maeM=round(s['ah'] / s['n'], 2),
                         biasFt=round(s['dft'] / s['nft'], 1) if s['nft'] else None,
                         maeFt=round(s['aft'] / s['nft'], 1) if s['nft'] else None))
    return dict(buoy=WATCH, days=VERIFY_DAYS, updated=now, lead=lead)


def main():
    fc_path, v0_path, waves_path, out = sys.argv[1:5]
    fc = load(fc_path, None)
    if not fc:
        print('No forecast this run; nothing to keep.')
        return
    now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    label = utc(fc['run']).strftime('%Y-%m-%d-%Hz')
    save(os.path.join(out, 'forecasts', f'{label}.json'), fc)
    v0 = load(v0_path, None)
    if v0 and v0.get('run') == fc['run']:
        save(os.path.join(out, 'forecasts-v0', f'{label}.json'), v0)
    names = keep_buoys(load(waves_path, {}), out)
    added = keep_hours(fc, out)
    v = verify(out, names, now)
    save(os.path.join(out, 'verify.json'), v)
    old = os.path.join(out, 'held.json')  # the first try: held swells, replaced by every hour
    if os.path.exists(old):
        os.unlink(old)
    print(f'{label}: {added} hourly predictions filed')
    for x in v['lead']:
        print(f"  {x['days']} days ahead: {x['n']} hours, height {x['biasM']:+.2f} m (typically {x['maeM']} m out)"
              + (f", size {x['biasFt']:+.1f} ft (typically {x['maeFt']} ft out)" if x['biasFt'] is not None else ''))


if __name__ == '__main__':
    main()
