"""Is the chart app's data fresh and readable? Run every hour by health.yml,
which fails (and opens an issue) when it isn't.

Reads the frames branch as a phone would: the manifest, then the first and
last frames it lists, each of which must unpack to the size the manifest's
grids give. The frames are published about 5 h after each of NOAA's runs
(00, 06, 12 and 18 UTC), so they're normally up to 6 h old; MAX_AGE_H allows
one run missed by a little, not two.

Standard library only:

  python scripts/check_fresh.py [FRAMES_URL]
"""
import gzip
import json
import sys
import time
import urllib.request

FRAMES = 'https://raw.githubusercontent.com/mattkirwan/north-sea-charts/frames/'
MAX_AGE_H = 9
H = 3600e3


def get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def frame_url(base, m, step):
    return f"{base}{m['dir'] + '/' if m.get('dir') else ''}f{step:0{m.get('pad', 3)}d}.bin.gz?run={m['run']}"


def problems(base, now_ms, fetch=get):
    """What's wrong with the published frames, as sentences; empty if nothing."""
    try:
        m = json.loads(fetch(f'{base}manifest.json?t={int(now_ms // 60e3)}'))
    except Exception as e:
        return [f'No manifest: {e}']
    out = []
    age = (now_ms - m['made']) / H
    if age > MAX_AGE_H:
        out.append(f"Frames last published {age:.0f} h ago (run {m['runLabel']}); expected within {MAX_AGE_H} h")
    if now_ms > m['run'] + m['steps'][-1] * H:
        out.append(f"Every frame of run {m['runLabel']} is in the past")
    P, S = m['grids']['p'], m['grids']['s']
    size = 4 * P * P + 2 * S * S
    for step in sorted({m['steps'][0], m['steps'][-1]}):
        url = frame_url(base, m, step)
        try:
            n = len(gzip.decompress(fetch(url)))
        except Exception as e:
            out.append(f'Frame +{step} h unreadable ({url}): {e}')
            continue
        if n != size:
            out.append(f'Frame +{step} h is {n} bytes; the grids make {size}')
    return out


if __name__ == '__main__':
    base = sys.argv[1] if len(sys.argv) > 1 else FRAMES
    found = problems(base, time.time() * 1000)
    for p in found:
        print(p)
    if not found:
        print('Frames fresh and readable')
    sys.exit(1 if found else 0)
