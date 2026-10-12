"""Which GFS run is the newest one complete on NOAA's open data bucket.

Standard library only, so the workflow can ask before installing anything:

  python scripts/gfs_latest.py      # prints e.g. "2026-10-12 06z"

NOAA starts a GFS run at 00, 06, 12 and 18 UTC. Its files reach the bucket
about 3 h 35 min later (forecast hour 0) and finish to hour 168, the last we
draw, about 4 h 15-35 min after the start (measured over Oct 2026).
"""
import datetime as dt
import urllib.request

BUCKET = 'https://noaa-gfs-bdp-pds.s3.amazonaws.com'
STEPS = list(range(0, 169, 6))


def grib_url(run, step):
    return f'{BUCKET}/gfs.{run:%Y%m%d}/{run:%H}/atmos/gfs.t{run:%H}z.pgrb2.0p25.f{step:03d}'


def exists(url):
    try:
        urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=30)
        return True
    except Exception:
        return False


def latest_run():
    """Newest run whose last frame is on the bucket."""
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    run = now.replace(hour=now.hour // 6 * 6)
    for _ in range(8):
        if exists(grib_url(run, STEPS[-1]) + '.idx'):
            return run
        run -= dt.timedelta(hours=6)
    raise SystemExit('No complete GFS run found in the last two days')


def label(run):
    return f'{run:%Y-%m-%d %H}z'


if __name__ == '__main__':
    print(label(latest_run()))
