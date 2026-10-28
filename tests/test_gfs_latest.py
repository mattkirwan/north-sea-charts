"""Which GFS run the jobs draw (scripts/gfs_latest.py): the newest whose last
frame is on NOAA's bucket, looking back a run at a time, against a made-up
bucket (exists() answered from a list of files)."""
import datetime as dt
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
import gfs_latest as gl  # noqa: E402

NOW = dt.datetime(2026, 10, 27, 14, 20, tzinfo=dt.timezone.utc)
R12, R06, R00 = (dt.datetime(2026, 10, 27, h, tzinfo=dt.timezone.utc) for h in (12, 6, 0))


def bucket(*urls):
    on = {u + '.idx' for u in urls}
    clock = mock.Mock(wraps=dt.datetime)
    clock.now.return_value = NOW
    return mock.patch.multiple(gl, exists=lambda url: url in on, dt=mock.Mock(datetime=clock, timedelta=dt.timedelta,
                                                                               timezone=dt.timezone))


class LatestRun(unittest.TestCase):
    def test_this_cycle_when_it_is_out(self):
        with bucket(gl.grib_url(R12, 120)):
            self.assertEqual(gl.latest_run(), R12)

    def test_steps_back_while_the_newest_is_still_coming(self):
        with bucket(gl.grib_url(R12, 6), gl.grib_url(R06, 120)):
            self.assertEqual(gl.latest_run(), R06)

    def test_full_needs_the_wave_model_out_to_384h_too(self):
        with bucket(gl.grib_url(R12, 384), gl.grib_url(R06, 384), gl.wave_grib_url(R06, 384)):
            self.assertEqual(gl.latest_run(full=True), R06)

    def test_nothing_in_two_days_stops_the_job(self):
        with bucket(gl.grib_url(R00 - dt.timedelta(days=3), 120)), self.assertRaises(SystemExit):
            gl.latest_run()

    def test_addresses(self):
        self.assertEqual(gl.grib_url(R06, 3), 'https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.20261027/06/atmos/gfs.t06z.pgrb2.0p25.f003')
        self.assertEqual(gl.label(R06), '2026-10-27 06z')


if __name__ == '__main__':
    unittest.main()
