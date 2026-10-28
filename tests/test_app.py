"""The chart app in a browser (Chromium, by Playwright): index.html and app.js
as served, reading a made-up run published the way chart_frames.py publishes
one (manifest.json and gzipped frames, encoded by its own encode()), from a
local server. It opens on the frame nearest now and draws it, the timeline
moves the forecast on, the bands switch and are remembered, and without a
manifest it says it's offline. Nothing leaves the machine: requests to any
other host (fonts, the usage stats) are dropped.

Skipped without Playwright (pip install playwright && playwright install
chromium), except on CI, where it must run. CHROMIUM=/path/to/chrome uses a
browser already on the machine.
"""
import datetime as dt
import functools
import gzip
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import chart_frames as cf  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STEPS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
ALL_IN = "!document.querySelector('.nss-timeline .nss-tick--pending')"   # every frame loaded


def fake_frame(P, S, k):
    """A low crossing the square (k moves it on), a high to the south, wind
    round the low and a swell that grows towards it; a band of land."""
    y, x = np.mgrid[0:1:P * 1j, 0:1:P * 1j]
    lx = 0.3 + 0.03 * k
    p = 1012 - 35 * np.exp(-((x - lx) ** 2 + (y - 0.4) ** 2) / 0.02) + 15 * np.exp(-((x - 0.6) ** 2 + (y - 0.85) ** 2) / 0.05)
    u, v = -(y - 0.4) * 40, (x - lx) * 40
    ys, xs = np.mgrid[0:1:S * 1j, 0:1:S * 1j]
    h = 1 + 6 * np.exp(-((xs - lx) ** 2 + (ys - 0.4) ** 2) / 0.05)
    t = 6 + 8 * xs
    land = (xs > 0.85)
    h[land], t[land] = np.nan, np.nan
    return p, u, v, h, t


def publish(out, run):
    """A run's manifest and frames, as run_frames() writes them."""
    d = cf.run_dir(run)
    os.makedirs(os.path.join(out, d))
    for k, s in enumerate(STEPS):
        with open(os.path.join(out, d, f'f{s:03d}.bin.gz'), 'wb') as f:
            f.write(gzip.compress(cf.encode(*fake_frame(cf.P_N, cf.S_N, k)), 6))
    ms = int(run.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    manifest = dict(ice=None, run=ms, runLabel=f'{run:%Y-%m-%d %H}z', made=ms, steps=STEPS, complete=True, dir=d,
                    file='{dir}/f{step}.bin.gz', pad=3, square=dict(x0=cf.X0, x1=cf.X1, y0=cf.Y0, y1=cf.Y1, proj=cf.PROJ4),
                    grids=dict(p=cf.P_N, s=cf.S_N), scale=cf.SCALE, encoding='row-delta-v1', source='made up')
    with open(os.path.join(out, 'manifest.json'), 'w') as f:
        json.dump(manifest, f)


class Handler(http.server.SimpleHTTPRequestHandler):
    """The repo at /, and the made-up frames branch at /_frames/."""
    frames = None

    def translate_path(self, path):
        if path.startswith('/_frames/'):
            return os.path.join(self.frames, path.split('?')[0][len('/_frames/'):])
        return super().translate_path(path)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, *a):
        pass


@unittest.skipIf(sync_playwright is None and not os.environ.get('CI'), 'Playwright not installed')
class App(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        # The run before last, so now is a few hours into it, as on the phone.
        cls.run_at = now.replace(minute=0, second=0, microsecond=0, hour=now.hour // 6 * 6) - dt.timedelta(hours=6)
        publish(os.path.join(cls.tmp, 'good'), cls.run_at)
        os.makedirs(os.path.join(cls.tmp, 'empty'))
        Handler.frames = cls.tmp
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=ROOT))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}'
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path=os.environ.get('CHROMIUM') or None)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp)

    def setUp(self):
        self.errors = []
        # None of the service worker: these are the page's own tests.
        self.new_page(service_workers='block')

    def new_page(self, **kw):
        """A phone's browser, with nothing let out beyond the local server."""
        if getattr(self, 'context', None):
            self.context.close()
        self.context = self.browser.new_context(viewport=dict(width=390, height=844), device_scale_factor=2,
                                                has_touch=True, **kw)
        self.context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(self.origin) else r.abort())
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.page.on('console', lambda m: m.type == 'error' and not self.dropped(m) and self.errors.append(m.text))

    def dropped(self, m):
        # The requests aborted above, and the 404s some tests ask for.
        return 'net::ERR_FAILED' in m.text or '404' in m.text

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def open(self, frames='good'):
        self.page.goto(f'{self.origin}/index.html?frames={self.origin}/_frames/{frames}/')

    def loaded(self):
        """Opened on a run, with the needle's frame drawn (the status clears)."""
        self.open()
        slider = self.page.locator('.nss-timeline')
        self.page.wait_for_function("document.querySelector('.nss-timeline').getAttribute('aria-valuemax') !== '0'")
        self.page.wait_for_function("document.querySelector('#rStatus').hidden")
        return slider

    def chart(self):
        self.page.evaluate('() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))')
        return hash(self.page.evaluate("document.querySelector('#chart').toDataURL()"))

    def test_opens_on_the_frame_nearest_now(self):
        slider = self.loaded()
        self.assertEqual(slider.get_attribute('aria-valuemax'), str(len(STEPS) - 1))
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        lead = round((now - self.run_at).total_seconds() / 3600)
        self.assertEqual(slider.get_attribute('aria-valuenow'), str(STEPS.index(lead)))
        self.assertEqual(self.page.locator('#panel [data-lead]').text_content(), f'+{lead}H')
        # One tick a frame, none still waiting once they're all in.
        self.assertEqual(self.page.locator('.nss-timeline .nss-tick:not(.nss-tick--day):not(.nss-tick--now)').count(), len(STEPS))
        self.page.wait_for_function(ALL_IN)

    def test_draws_the_chart(self):
        self.loaded()
        blank = self.page.evaluate("""(() => { const c = document.createElement('canvas'), q = document.querySelector('#chart');
            c.width = q.width; c.height = q.height; return c.toDataURL(); })()""")
        blank = hash(blank)
        pressure = self.chart()
        self.assertNotEqual(pressure, blank)
        for band in ('wind', 'swell'):
            self.page.click(f'#panel .nss-band[data-band="{band}"]')
            self.assertNotEqual(self.chart(), pressure, band)

    def test_timeline_keys_move_the_forecast(self):
        slider = self.loaded()
        slider.focus()
        self.page.keyboard.press('Home')
        self.assertEqual(slider.get_attribute('aria-valuenow'), '0')
        self.assertEqual(self.page.locator('#panel [data-lead]').text_content(), '+0H')
        first = self.chart()
        self.page.keyboard.press('ArrowRight')
        self.assertEqual(self.page.locator('#panel [data-lead]').text_content(), '+1H')
        self.assertNotEqual(self.chart(), first)
        self.page.keyboard.press('End')
        self.assertEqual(slider.get_attribute('aria-valuenow'), str(len(STEPS) - 1))
        self.assertEqual(self.page.locator('#panel [data-lead]').text_content(), f'+{STEPS[-1]}H')
        self.page.keyboard.press('ArrowRight')                       # no further than the last frame
        self.assertEqual(slider.get_attribute('aria-valuenow'), str(len(STEPS) - 1))

    def test_band_is_remembered(self):
        self.loaded()
        self.page.click('#panel .nss-band[data-band="swell"]')
        self.assertEqual(self.page.locator('#panel [data-swell]').is_hidden(), False)
        self.page.reload()
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="swell"]').get_attribute('aria-pressed'), 'true')
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="pressure"]').get_attribute('aria-pressed'), 'false')

    def test_docks_and_opens_again(self):
        self.loaded()
        self.page.click('#panel .nss-dock-btn')
        self.page.wait_for_function("document.querySelector('#panel').hasAttribute('data-away')")
        self.assertEqual(self.page.locator('#column').get_attribute('data-away'), None)
        self.page.click('#column .nss-dock-btn')
        self.page.wait_for_function("document.querySelector('#column').hasAttribute('data-away')")

    def test_opens_without_a_signal(self):
        # sw.js keeps the page, the app and the frames seen: with no network
        # the app opens again on the same run, and says it's offline.
        self.new_page()
        self.loaded()
        self.page.wait_for_function('!!navigator.serviceWorker.controller')
        self.page.reload()                                            # now through the worker, which keeps what it serves
        self.page.wait_for_function("document.querySelector('#rStatus').hidden")
        self.page.wait_for_function(ALL_IN)
        self.context.set_offline(True)
        self.page.reload()
        self.page.wait_for_function("document.querySelector('#rStatus').textContent.startsWith('Offline · run')")
        self.assertEqual(self.page.locator('.nss-timeline').get_attribute('aria-valuemax'), str(len(STEPS) - 1))
        self.page.wait_for_function("""(() => { const s = document.querySelector('.nss-timeline'),
            ticks = s.querySelectorAll('.nss-tick:not(.nss-tick--day):not(.nss-tick--now)');
            return !ticks[+s.getAttribute('aria-valuenow')].classList.contains('nss-tick--pending'); })()""")

    def test_no_manifest_says_offline(self):
        self.open('empty')
        self.page.wait_for_function("document.querySelector('#rStatus').textContent === 'Offline'")


if __name__ == '__main__':
    unittest.main()
