"""What's published on one of our branches, for the workflows to compare
against NOAA's newest run (gfs_latest.py). Standard library only:

  python scripts/published.py URL            # "2026-10-27 12z", or
                                              # "2026-10-27 12z partial" if it
                                              # stopped short; nothing if none
  python scripts/published.py URL --frames   # how many frames it has

A partial run (chart_frames.py publishes one with 60% of its frames or more)
never matches NOAA's label, so the loop tries it again.
"""
import json
import sys
import time
import urllib.request


def published(url):
    try:
        with urllib.request.urlopen(f'{url}manifest.json?t={int(time.time())}', timeout=30) as r:
            return json.load(r)
    except Exception:
        return None


def label(m):
    if not m:
        return ''
    return m['runLabel'] + ('' if m.get('complete', True) else ' partial')


if __name__ == '__main__':
    m = published(sys.argv[1])
    print(len(m['steps']) if m and '--frames' in sys.argv else '' if '--frames' in sys.argv else label(m))
