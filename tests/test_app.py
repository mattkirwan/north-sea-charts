"""The chart app in a browser (Chromium, by Playwright): index.html and app.js
as served, reading a made-up run published the way chart_frames.py publishes
one (manifest.json and gzipped frames, encoded by its own encode()), from a
local server. It opens on the frame nearest now and draws it, the timeline
moves the forecast on, play runs it on to the last frame (and a touch on
the timeline pauses it), the bands switch and are remembered, the menu opens
and closes as a sheet (keyboard, scrim, grip) with feedback, and the panel
and hand settings, in it, and without a manifest it says it's offline. The first-use
tips wait for a quiet moment, go once done, tapped or left, and are kept
(with the release someone first came on), with storage or without. On first open it
asks which language, with the phone's own picked; Settings › Language changes
it, and it's remembered. Nothing leaves the machine: requests to any
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
import re
import shutil
import sys
import tempfile
import threading
import time
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


def publish(out, run, cells=False):
    """A run's manifest and frames, as run_frames() writes them; and its
    cell tiles if cells (made up as in test_grid.py)."""
    d = cf.run_dir(run)
    os.makedirs(os.path.join(out, d))
    for k, s in enumerate(STEPS):
        with open(os.path.join(out, d, f'f{s:03d}.bin.gz'), 'wb') as f:
            f.write(gzip.compress(cf.encode(*fake_frame(cf.P_N, cf.S_N, k)), 6))
    ms = int(run.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    manifest = dict(ice=None, run=ms, runLabel=f'{run:%Y-%m-%d %H}z', made=ms, steps=STEPS, complete=True, dir=d,
                    file='{dir}/f{step}.bin.gz', pad=3, square=dict(x0=cf.X0, x1=cf.X1, y0=cf.Y0, y1=cf.Y1, proj=cf.PROJ4),
                    grids=dict(p=cf.P_N, s=cf.S_N), scale=cf.SCALE, encoding='row-delta-v1', source='made up')
    if cells:
        from test_grid import fake_boxes
        manifest['cells'] = cf.cell_tiles(out, run, STEPS, fake_boxes(STEPS))
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
        publish(os.path.join(cls.tmp, 'cells'), cls.run_at, cells=True)
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

    def new_page(self, first_open=False, **kw):
        """A phone's browser, with nothing let out beyond the local server: one
        that has opened the app before and kept English, unless first_open."""
        if getattr(self, 'context', None):
            self.context.close()
        self.context = self.browser.new_context(viewport=dict(width=390, height=844), device_scale_factor=2,
                                                has_touch=True, **kw)
        if not first_open:
            self.context.add_init_script("try { if (localStorage.getItem('nss.lang') == null) localStorage.setItem('nss.lang', '\"en\"'); } catch (e) {}")
        self.context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(self.origin) else r.abort())
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.page.on('console', lambda m: m.type == 'error' and not self.dropped(m) and self.errors.append(m.text))

    def dropped(self, m):
        # The requests aborted above, and the 404s and 502s some tests ask for.
        return 'net::ERR_FAILED' in m.text or '404' in m.text or '502' in m.text

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

    # ---- Hints (hints.js) -----------------------------------------------------------
    def tip(self):
        """The tip showing, by its words, or None."""
        return self.page.evaluate("(() => { const t = [...document.querySelectorAll('[data-tip]')].find((t) => !t.hidden);"
                                  " return t ? t.textContent : null; })()")

    def tip_due(self, words):
        self.page.wait_for_function(f"[...document.querySelectorAll('[data-tip]')].some((t) => !t.hidden && t.textContent === {json.dumps(words)})")

    def hints(self):
        return self.page.evaluate("JSON.parse(localStorage.getItem('nss.hints.v1'))")

    def slide(self):
        b = self.box('#panel .nss-timeline')
        x, y = b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.mouse.move(x - 60, y, steps=6)
        self.page.mouse.up()

    def test_tips_wait_for_quiet_then_go_once_done(self):
        self.loaded()
        # Not while someone's busy with the chart: 1.5 s of quiet first.
        for _ in range(5):
            self.page.mouse.click(150, 200)
            self.page.wait_for_timeout(600)
            self.assertIsNone(self.tip())
        self.tip_due('Slide timeline')
        self.assertTrue(self.page.locator('#panel [data-tip]').is_visible())
        # On top of the needle's arrow, centred over it (once it's slid in).
        self.page.wait_for_timeout(400)
        tip, arrow = self.box('#panel [data-tip]'), self.box('#panel .nss-timeline-arrow')
        self.assertAlmostEqual(tip['x'] + tip['width'] / 2, arrow['x'] + arrow['width'] / 2, delta=1)
        self.assertLessEqual(tip['y'] + tip['height'], arrow['y'])
        self.slide()
        self.assertIsNone(self.tip())
        self.assertEqual(self.hints()['seen'], {'tip.timeline.slide': 'retired'})
        # Then the next in the chain, once the timeline has settled.
        self.tip_due('Double-tap to reset')
        b = self.box('#panel .nss-timeline')
        self.page.mouse.dblclick(b['x'] + 80, b['y'] + b['height'] / 2)
        self.assertIsNone(self.tip())
        self.assertEqual(self.hints()['seen'], {'tip.timeline.slide': 'retired', 'tip.timeline.reset': 'retired'})
        self.page.reload()
        self.page.wait_for_function("document.querySelector('.nss-timeline').getAttribute('aria-valuemax') !== '0'")
        self.page.wait_for_timeout(2500)
        self.assertIsNone(self.tip())

    def test_a_tip_dims_at_a_touch_goes_untouched_and_goes_when_tapped(self):
        self.loaded()
        self.tip_due('Slide timeline')
        self.page.mouse.click(150, 200)
        self.assertEqual(self.page.locator('#panel [data-tip]').get_attribute('data-fading'), '')
        self.page.wait_for_function("document.querySelector('#panel [data-tip]').hidden", timeout=8000)
        self.assertEqual(self.hints()['seen'], {'tip.timeline.slide': 'retired'})
        self.tip_due('Double-tap to reset')
        b = self.box('#panel [data-tip]')
        self.page.mouse.click(b['x'] + b['width'] / 2, b['y'] + b['height'] / 2)
        self.assertIsNone(self.tip())
        self.assertEqual(self.hints()['seen']['tip.timeline.reset'], 'retired')

    def test_the_tip_shows_in_the_docked_column(self):
        self.context.add_init_script("localStorage.setItem('nss.docked', 'true')")
        self.loaded()
        self.tip_due('Slide timeline')
        self.assertTrue(self.page.locator('#column [data-tip]').is_visible())
        self.assertTrue(self.page.locator('#panel [data-tip]').is_hidden())

    def test_tips_seen_before_hints_stay_seen(self):
        self.context.add_init_script("localStorage.setItem('nss.tip1', 'true'); localStorage.setItem('nss.tip2', 'true')")
        self.loaded()
        self.page.wait_for_timeout(2500)
        self.assertIsNone(self.tip())
        h = self.hints()
        self.assertEqual(h['seen'], {'tip.timeline.slide': 'retired', 'tip.timeline.reset': 'retired'})
        self.assertEqual(h['firstSeenRelease'], '0')            # here before: before every release
        self.assertTrue(h['tipsOn'])

    def stamped(self, release):
        """index.html as a deploy serves it, stamped with its release (the last one given)."""
        def serve(route):
            r = route.fetch()
            route.fulfill(response=r, body=r.text().replace('data-release="dev"', f'data-release="{self.release}"'))
        if getattr(self, 'release', None) is None:
            self.page.route(lambda url: '/index.html' in url, serve)
        self.release = release

    def test_a_first_visit_keeps_the_release_it_came_on(self):
        self.new_page(first_open=True, service_workers='block')
        self.stamped('2026-11-02-1200')
        self.open()
        self.page.wait_for_function("localStorage.getItem('nss.hints.v1')")
        self.assertEqual(self.hints()['firstSeenRelease'], '2026-11-02-1200')
        self.stamped('2026-11-09-1200')                         # still the first one, on a later release
        self.page.reload()
        self.page.wait_for_function("localStorage.getItem('nss.hints.v1')")
        self.assertEqual(self.hints()['firstSeenRelease'], '2026-11-02-1200')

    def test_the_first_visit_to_a_development_copy_keeps_no_release(self):
        self.new_page(first_open=True, service_workers='block')
        self.open()
        self.page.wait_for_function("localStorage.getItem('nss.hints.v1')")
        self.assertIsNone(self.hints()['firstSeenRelease'])

    def test_tips_without_storage(self):
        self.context.add_init_script("""for (const k of ['localStorage', 'sessionStorage'])
            Object.defineProperty(window, k, { get() { throw new DOMException('denied', 'SecurityError'); } });""")
        self.open()
        self.page.wait_for_function("document.querySelector('.nss-timeline').getAttribute('aria-valuemax') !== '0'")
        # Nothing kept, so it's a first open: the language first, then the tip.
        self.page.keyboard.press('Escape')
        self.closed()
        self.tip_due('Slide timeline')
        self.slide()
        self.assertIsNone(self.tip())

    def news(self):
        """hints.js with a new feature of the tests' own (none ships): the side panel, in words already there."""
        entry = ("{ id: 'new.panel.side', type: 'new', target: 'menu-button', path: ['menu-button', 'menu.settings', 'settings.panel'], "
                 "since: '2026-10-29', name: 'side', kicker: 'settings', title: 'panel', body: 'panelSub', action: 'open-settings:panel', "
                 "doneEvent: 'panel.changed' }")
        def serve(route):
            r = route.fetch()
            route.fulfill(response=r, body=r.text().replace('\n];', f',\n  {entry}\n];'))
        self.page.route(lambda url: '/hints.js' in url, serve)

    def kept(self, news=False, **kept):
        """Someone who's had the timeline's tips, so this visit's one new hint is free, with anything else
        kept; and a new feature to hear about, with news."""
        seen = {'tip.timeline.slide': 'retired', 'tip.timeline.reset': 'retired'}
        if news:
            self.news()
        kept = {'nss.hints.v1': dict(firstSeenRelease='0', tipsOn=True, seen=seen, guideCompleted=False), **kept}
        # The hints' own state once, so what a test does to it survives a reload.
        self.context.add_init_script(''.join((f'if (localStorage.getItem({json.dumps(k)}) == null) ' if k == 'nss.hints.v1' else '') +
                                             f'localStorage.setItem({json.dumps(k)}, {json.dumps(json.dumps(v))});' for k, v in kept.items()))

    def swell_tip(self, panel, words='Tap for wave period'):
        """Swell chosen in the panel showing: the tip floats over Period, on the screen, notched to it, and goes once Period's chosen."""
        self.page.click(f'{panel} .nss-band[data-band="swell"]')
        self.tip_due(words)
        self.page.wait_for_timeout(400)                         # slid in
        tag, notch = self.box('[data-tip-float]'), self.box('[data-tip-float] .nss-tip-notch')
        period = self.box(f'{panel} [data-hint-point="period"]')
        self.assertGreaterEqual(tag['x'], 0)
        self.assertLessEqual(tag['x'] + tag['width'], 390)
        self.assertLessEqual(tag['y'] + tag['height'], period['y'])
        self.assertTrue(period['x'] <= notch['x'] + notch['width'] / 2 <= period['x'] + period['width'])
        if panel == '#column':                                  # and off the column's buttons
            col = self.box('#column .nss-bands')
            self.assertTrue(tag['x'] + tag['width'] <= col['x'] or tag['x'] >= col['x'] + col['width'])
        self.page.click(f'{panel} [data-hint-point="period"]')
        self.assertIsNone(self.tip())
        self.assertEqual(self.hints()['seen']['tip.swell.period'], 'retired')

    def test_the_swell_tip_points_at_period_in_either_panel_with_either_hand(self):
        for docked in (False, True):
            for hand in ('right', 'left'):
                with self.subTest(docked=docked, hand=hand):
                    self.new_page(service_workers='block')
                    self.kept(**{'nss.docked': docked, 'nss.hand': hand})
                    self.loaded()
                    self.swell_tip('#column' if docked else '#panel')

    def test_the_swell_tip_fits_in_the_longest_language(self):
        self.kept(**{'nss.lang': 'de', 'nss.hand': 'left'})
        self.loaded()
        self.swell_tip('#panel', 'Für Wellenperiode tippen')

    def test_the_swell_tip_waits_while_swell_is_off_and_isnt_needed_on_period(self):
        self.kept()
        self.loaded()
        self.page.click('#panel .nss-band[data-band="swell"]')
        self.tip_due('Tap for wave period')
        self.page.click('#panel .nss-band[data-band="wind"]')
        self.assertIsNone(self.tip())
        self.assertNotIn('tip.swell.period', self.hints()['seen'])
        self.page.click('#panel .nss-band[data-band="swell"]')
        self.tip_due('Tap for wave period')
        self.new_page(service_workers='block')
        self.kept(**{'nss.swell': 'period'})
        self.loaded()
        self.page.click('#panel .nss-band[data-band="swell"]')
        self.page.wait_for_timeout(2500)
        self.assertIsNone(self.tip())

    def test_one_new_tip_a_visit(self):
        self.loaded()
        self.tip_due('Slide timeline')
        self.slide()
        self.page.click('#panel .nss-band[data-band="swell"]')
        # The timeline's second tip is the same new one; the swell tip waits for another visit.
        self.tip_due('Double-tap to reset')
        b = self.box('#panel .nss-timeline')
        self.page.mouse.dblclick(b['x'] + 80, b['y'] + b['height'] / 2)
        self.page.wait_for_timeout(2500)
        self.assertIsNone(self.tip())
        self.page.reload()
        self.page.wait_for_function("document.querySelector('.nss-timeline').getAttribute('aria-valuemax') !== '0'")
        self.page.wait_for_timeout(2500)
        self.assertIsNone(self.tip())

    def test_tips_off_stays_off_until_shown_again(self):
        self.loaded()
        self.tip_due('Slide timeline')
        self.setting('tips', 'off')
        self.assertIsNone(self.tip())
        self.assertEqual(self.page.locator('[data-set="tips"] [data-value="off"]').get_attribute('aria-pressed'), 'true')
        h = self.hints()
        self.assertFalse(h['tipsOn'])
        self.assertEqual(sorted(h['seen']), ['tip.swell.period', 'tip.timeline.reset', 'tip.timeline.slide'])
        self.page.reload()
        self.page.wait_for_function("document.querySelector('.nss-timeline').getAttribute('aria-valuemax') !== '0'")
        self.page.click('#panel .nss-band[data-band="swell"]')
        self.page.wait_for_timeout(2500)
        self.assertIsNone(self.tip())
        self.page.click('#panel [data-menu]')
        self.page.click('[data-go="settings"]')
        self.assertEqual(self.page.locator('[data-set="tips"] [data-value="off"]').get_attribute('aria-pressed'), 'true')
        self.page.click('[data-tips-again]')
        self.assertEqual(self.page.locator('[data-tips-again] .nss-menu-sub').text_content(), "They'll show again")
        self.assertEqual(self.page.locator('[data-set="tips"] [data-value="on"]').get_attribute('aria-pressed'), 'true')
        self.assertEqual(self.hints()['seen'], {})
        self.assertTrue(self.hints()['tipsOn'])
        # Not over the menu: once it's closed, from the start (Swell's on, so its tip first).
        self.page.wait_for_timeout(2000)
        self.assertIsNone(self.tip())
        self.page.keyboard.press('Escape')
        self.closed()
        self.tip_due('Tap for wave period')

    # ---- New features (hints.js, type 'new') ------------------------------------------
    def light(self, sel):
        """The light on a control: None, 'steady' or 'ping'."""
        return self.page.evaluate(f"""(() => {{ const l = document.querySelector({json.dumps(sel)} + ' > .nss-light');
            return l ? (l.classList.contains('nss-light--ping') ? 'ping' : 'steady') : null; }})()""")

    def tag_due(self):
        self.page.wait_for_function("!document.querySelector('[data-new-tag]').hidden")
        self.page.wait_for_timeout(400)                         # slid in

    def on_screen(self, sel):
        b = self.box(sel)
        self.assertGreaterEqual(b['x'], 0)
        self.assertLessEqual(b['x'] + b['width'], 390)
        self.assertGreaterEqual(b['y'], 0)
        return b

    def test_the_side_panel_news_runs_through_every_state(self):
        self.kept(news=True)
        self.loaded()
        self.tag_due()
        menu = '#panel [data-menu]'
        self.assertEqual(self.light(menu), 'ping')
        self.assertEqual(self.page.locator('[data-new-tag]').text_content(), 'New · Side')
        self.assertEqual(self.page.locator(menu).get_attribute('aria-label'), 'Menu, something new')
        tag, btn = self.on_screen('[data-new-tag]'), self.box(menu)
        self.assertLessEqual(tag['y'] + tag['height'], btn['y'])
        # The card: focus in it, the light steady, the chart still there to touch.
        self.page.click('[data-new-tag]')
        self.assertTrue(self.page.locator('[data-hint-card]').is_visible())
        self.assertEqual(self.page.locator('[data-hint-card]').get_attribute('role'), 'dialog')
        self.assertEqual(self.focused(), 'Show me')
        self.assertEqual(self.light(menu), 'steady')
        self.on_screen('[data-hint-card]')
        self.page.mouse.click(150, 200)                         # tapped away from: its light left on
        self.assertTrue(self.page.locator('[data-hint-card]').is_hidden())
        self.assertEqual(self.light(menu), 'steady')
        self.assertEqual(self.hints()['seen']['new.panel.side'], 'quiet')
        self.page.reload()
        self.page.wait_for_function("document.querySelector('.nss-timeline').getAttribute('aria-valuemax') !== '0'")
        self.page.wait_for_timeout(2500)
        self.assertTrue(self.page.locator('[data-new-tag]').is_hidden())
        self.assertEqual(self.light(menu), 'steady')
        # The way to it: Settings in the menu, then the Panel row.
        self.page.click(menu)
        self.assertEqual(self.light('[data-go="settings"]'), 'steady')
        self.page.click('[data-go="settings"]')
        self.assertEqual(self.light('[data-hint-target="settings.panel"]'), 'steady')
        # Used: gone, every light with it.
        self.page.click('[data-set="panel"] [data-value="side"]')
        self.assertEqual(self.hints()['seen']['new.panel.side'], 'retired')
        self.assertEqual(self.page.locator('.nss-light').count(), 0)
        self.assertEqual(self.page.locator('#column [data-menu]').get_attribute('aria-label'), 'Menu')

    def test_the_news_ignored_leaves_its_light(self):
        self.kept(news=True)
        self.loaded()
        self.tag_due()
        self.page.wait_for_function("document.querySelector('[data-new-tag]').hidden", timeout=8000)
        self.assertEqual(self.hints()['seen']['new.panel.side'], 'quiet')
        self.assertEqual(self.light('#panel [data-menu]'), 'steady')

    def test_the_cards_buttons(self):
        for button in ('got-it', 'show-me', 'escape'):
            with self.subTest(button=button):
                self.new_page(service_workers='block')
                self.kept(news=True)
                self.loaded()
                self.tag_due()
                self.page.click('[data-new-tag]')
                if button == 'escape':
                    self.page.keyboard.press('Escape')
                    self.assertEqual(self.hints()['seen']['new.panel.side'], 'quiet')
                    self.assertTrue(self.page.evaluate("document.activeElement === document.querySelector('#panel [data-menu]')"))
                    continue
                self.page.click(f'[data-{button}]')
                self.assertEqual(self.hints()['seen']['new.panel.side'], 'retired')
                self.assertEqual(self.page.locator('.nss-light').count(), 0)
                if button == 'show-me':                         # Settings, at the Panel switch
                    self.assertEqual(self.shown(), 'Settings')
                    self.assertTrue(self.page.evaluate("!!document.activeElement.closest('[data-set=\"panel\"]')"))

    def test_docked_the_news_sits_beside_the_column(self):
        for hand in ('right', 'left'):
            with self.subTest(hand=hand):
                self.new_page(service_workers='block')
                self.kept(news=True, **{'nss.docked': True, 'nss.hand': hand})
                self.loaded()
                self.tag_due()
                col, btn = self.box('#column'), self.box('#column [data-menu]')
                for sel in ('[data-new-tag]', '[data-hint-card]'):
                    if sel == '[data-hint-card]':
                        self.page.click('[data-new-tag]')
                    b = self.on_screen(sel)
                    if hand == 'right':
                        self.assertLessEqual(b['x'] + b['width'], col['x'])
                    else:
                        self.assertGreaterEqual(b['x'], col['x'] + col['width'])
                    self.assertTrue(b['y'] <= btn['y'] + btn['height'] / 2 <= b['y'] + b['height'])   # level with it

    def test_the_news_fits_in_the_longest_language(self):
        self.kept(news=True, **{'nss.lang': 'fr'})
        self.loaded()
        self.tag_due()
        self.assertEqual(self.page.locator('[data-new-tag]').text_content(), 'Nouveau · Côté')
        self.on_screen('[data-new-tag]')
        self.page.click('[data-new-tag]')
        self.on_screen('[data-hint-card]')
        for b in ('[data-got-it]', '[data-show-me]'):           # each word on its button
            self.assertLessEqual(self.page.evaluate(f"(() => {{ const b = document.querySelector('{b}'); return b.scrollWidth - b.clientWidth; }})()"), 0)

    def test_only_people_who_came_before_it_get_the_news(self):
        for first, lit in (('2026-10-01-1200', True), ('2026-11-02-1200', False)):
            with self.subTest(first=first):
                self.new_page(first_open=True, service_workers='block')
                self.release = None
                self.news()
                self.stamped(first)
                self.open()
                self.page.wait_for_function("document.querySelector('.nss-timeline').getAttribute('aria-valuemax') !== '0'")
                self.page.keyboard.press('Escape')              # the language, asked on first open
                self.closed()
                self.assertEqual(self.light('#panel [data-menu]'), 'steady' if lit else None)
                if lit:                                         # this visit's one new hint is the timeline's tip
                    self.tip_due('Slide timeline')
                    self.slide()
                    self.page.wait_for_timeout(2500)
                    self.assertTrue(self.page.locator('[data-new-tag]').is_hidden())

    def test_nothing_new_is_announced_for_now(self):
        self.kept()
        self.loaded()
        self.page.wait_for_timeout(2500)
        self.assertEqual(self.page.locator('.nss-light').count(), 0)
        self.assertTrue(self.page.locator('[data-new-tag]').is_hidden())
        self.assertEqual(self.page.locator('#panel [data-menu]').get_attribute('aria-label'), 'Menu')

    def test_no_lights_with_tips_off(self):
        self.kept(news=True)
        self.loaded()
        self.setting('tips', 'off')
        self.assertEqual(self.page.locator('.nss-light').count(), 0)

    # ---- The Guide (Menu › Guide) ------------------------------------------------------
    def guide(self):
        self.page.click('#panel:not([inert]) [data-menu], #column:not([inert]) [data-menu]')
        self.page.click('[data-guide]')
        self.page.wait_for_function("!document.querySelector('[data-guide-card]').hidden")

    def step(self):
        """The step showing, by its card's label, or None once the Guide's gone."""
        card = self.page.locator('[data-guide-card]')
        return None if card.is_hidden() else card.get_attribute('aria-label')

    def lit(self):
        return self.page.evaluate("[...document.querySelectorAll('.nss-spot')].map((e) => e.dataset.hintTarget)")

    def tried(self):
        return self.page.locator('[data-guide-try]').get_attribute('data-done') is not None

    def guide_card_clear_of(self, panel):
        """The card on the screen, clear of what's lit (and of the column, docked), and notched to it."""
        self.page.wait_for_timeout(300)
        card = self.box('[data-guide-card]')
        self.assertGreaterEqual(card['x'], 0)
        self.assertLessEqual(card['x'] + card['width'], 390)
        self.assertGreaterEqual(card['y'], 0)
        spot = self.page.locator('.nss-spot')
        if spot.count():
            s = spot.bounding_box()
            self.assertTrue(card['y'] + card['height'] <= s['y'] or card['x'] + card['width'] <= s['x'] or card['x'] >= s['x'] + s['width'])
        if panel == '#column':
            col = self.box('#column')
            self.assertTrue(card['x'] + card['width'] <= col['x'] or card['x'] >= col['x'] + col['width'])
        else:
            self.assertLessEqual(card['y'] + card['height'], self.box('#panel')['y'] - 11)

    def test_the_guide_goes_round_the_chart_and_puts_the_band_back(self):
        self.kept()
        self.loaded()
        self.guide()
        self.closed()                                           # the menu's gone; the Guide's over the chart
        self.assertEqual(self.step(), 'Guide, step 1 of 4')
        self.assertEqual(self.page.locator('[data-guide-card]').get_attribute('role'), 'dialog')
        self.assertEqual(self.focused(), 'Next')
        # 1: the chart itself, live, the panel dimmed; no Back.
        self.assertEqual(self.lit(), [])
        self.assertTrue(self.page.locator('[data-guide-scrim]').is_hidden())
        self.assertTrue(self.page.locator('#panel > .nss-guide-scrim').is_visible())
        self.assertTrue(self.page.locator('[data-guide-back]').is_hidden())
        self.guide_card_clear_of('#panel')
        self.assertFalse(self.tried())
        self.page.mouse.move(150, 200)
        self.page.mouse.wheel(0, -200)
        self.assertTrue(self.tried())
        # 2: the bands, the rest dimmed, the chart too.
        self.page.click('[data-guide-next]')
        self.assertEqual(self.step(), 'Guide, step 2 of 4')
        self.assertEqual(self.lit(), ['bands'])
        self.assertTrue(self.page.locator('[data-guide-scrim]').is_visible())
        self.guide_card_clear_of('#panel')
        # 3: the key, on Swell, Period live.
        self.page.click('[data-guide-next]')
        self.assertEqual(self.lit(), ['key'])
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="swell"]').get_attribute('aria-pressed'), 'true')
        self.guide_card_clear_of('#panel')
        self.page.click('#panel [data-var="period"]')
        self.assertTrue(self.tried())
        self.assertEqual(self.step(), 'Guide, step 3 of 4')    # never moves on by itself
        # Back, and forward again: still ticked.
        self.page.click('[data-guide-back]')
        self.assertEqual(self.step(), 'Guide, step 2 of 4')
        self.page.click('[data-guide-next]')
        self.assertTrue(self.tried())
        # 4: the timeline, slid and brought back to now; Done.
        self.page.click('[data-guide-next]')
        self.assertEqual(self.lit(), ['timeline'])
        self.assertEqual(self.page.locator('[data-guide-next]').text_content(), 'Done')
        self.guide_card_clear_of('#panel')
        self.slide()
        self.assertFalse(self.tried())
        b = self.box('#panel .nss-timeline')
        self.page.mouse.dblclick(b['x'] + 80, b['y'] + b['height'] / 2)
        self.assertTrue(self.tried())
        self.page.click('[data-guide-next]')
        self.assertIsNone(self.step())
        self.assertEqual(self.lit(), [])
        self.assertEqual(self.page.locator('.nss-guide-scrim:visible').count(), 0)
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="pressure"]').get_attribute('aria-pressed'), 'true')
        self.assertEqual(self.page.evaluate("localStorage.getItem('nss.band')"), '"pressure"')
        self.assertTrue(self.page.evaluate("document.activeElement === document.querySelector('#panel [data-menu]')"))
        h = self.hints()
        self.assertTrue(h['guideCompleted'])
        self.assertEqual(h['seen']['tip.swell.period'], 'retired')

    def test_the_guide_closes_from_any_step(self):
        for how in ('close', 'escape', 'back'):
            with self.subTest(how=how):
                self.new_page(service_workers='block')
                self.loaded()
                self.guide()
                self.page.click('[data-guide-next]')
                self.page.click('[data-guide-next]')                # on Swell for the key
                self.assertEqual(self.step(), 'Guide, step 3 of 4')
                if how == 'close':
                    self.page.click('[data-guide-close]')
                elif how == 'escape':
                    self.page.keyboard.press('Escape')
                else:
                    self.page.go_back()                             # the phone's back gesture
                self.page.wait_for_function("document.querySelector('[data-guide-card]').hidden")
                self.assertEqual(self.lit(), [])
                self.assertEqual(self.page.locator('#panel .nss-band[data-band="pressure"]').get_attribute('aria-pressed'), 'true')
                h = self.hints()
                self.assertFalse(h['guideCompleted'])
                # Taught already: the tips it covers don't come after it.
                self.assertEqual({k for k, v in h['seen'].items() if v == 'retired'}, {'tip.timeline.slide', 'tip.timeline.reset', 'tip.swell.period'})
                self.page.wait_for_timeout(2000)
                self.assertIsNone(self.tip())
                self.assertIn('/index.html', self.page.url)          # back closed the Guide, not the app

    def test_no_tips_while_the_guide_is_on(self):
        self.loaded()
        self.guide()                                            # before the first tip's due
        self.page.wait_for_timeout(2500)
        self.assertIsNone(self.tip())

    def test_the_guide_in_the_docked_column_with_either_hand(self):
        for hand in ('right', 'left'):
            with self.subTest(hand=hand):
                self.new_page(service_workers='block')
                self.kept(**{'nss.docked': True, 'nss.hand': hand})
                self.loaded()
                self.guide()
                for target in (None, 'bands', 'key', 'timeline'):
                    self.assertEqual(self.lit(), [target] if target else [])
                    self.guide_card_clear_of('#column')
                    self.page.click('[data-guide-next]')
                self.assertIsNone(self.step())

    def test_the_guide_fits_in_the_longest_language(self):
        self.kept(**{'nss.lang': 'de'})
        self.loaded()
        self.guide()
        self.assertEqual(self.step(), 'Rundgang, Schritt 1 von 4')
        for _ in range(4):
            self.guide_card_clear_of('#panel')
            self.page.click('[data-guide-next]')

    # ---- The menu ------------------------------------------------------------------
    def box(self, sel):
        return self.page.locator(sel).bounding_box()

    def shown(self):
        """The sheet showing, by its label, or None once the menu has closed."""
        return self.page.evaluate("(() => { const s = [...document.querySelectorAll('[data-sheet]')].find((s) => !s.hidden);"
                                  " return s ? s.getAttribute('aria-label') : null; })()")

    def closed(self):
        self.page.wait_for_function("[...document.querySelectorAll('[data-sheet]')].every((s) => s.hidden) && document.querySelector('#scrim').hidden")

    def focused(self):
        return self.page.evaluate("(() => { const a = document.activeElement; return a.getAttribute('aria-label') || a.textContent.trim(); })()")

    def setting(self, name, value):
        """Menu › Settings › name › value, from the menu button showing; leaves Settings open."""
        if self.shown() is None:
            self.page.click('#panel:not([inert]) [data-menu], #column:not([inert]) [data-menu]')
        if self.shown() != 'Settings':
            self.page.click('[data-go="settings"]')
        self.page.click(f'[data-set="{name}"] [data-value="{value}"]')

    def test_one_menu_button_in_the_same_spot(self):
        self.loaded()
        self.assertEqual(self.page.locator('.nss-dock-btn').count(), 0)
        for b in ('#panel [data-menu]', '#column [data-menu]'):
            self.assertEqual(self.page.locator(b).get_attribute('aria-label'), 'Menu')
            self.assertEqual(self.page.locator(b).get_attribute('aria-haspopup'), 'dialog')
        for hand, x in (('right', 390 - 12 - 48), ('left', 12)):
            if hand == 'left':
                self.setting('hand', 'left')
                self.setting('panel', 'bottom')
                self.page.keyboard.press('Escape')
                self.closed()
            self.page.wait_for_function("!document.querySelector('#panel').hasAttribute('data-away')")
            open_ = self.box('#panel [data-menu]')
            self.setting('panel', 'side')
            self.page.wait_for_function("getComputedStyle(document.querySelector('#column')).opacity === '1'")
            side = self.box('#column [data-menu]')
            for b in (open_, side):
                self.assertEqual((round(b['x']), round(b['width']), round(b['height'])), (x, 48, 44), hand)
            self.assertEqual(round(open_['y']), round(side['y']), hand)
            # The close button takes the same spot, so the same thumb closes it.
            self.page.click('#settings [data-back]')
            close = self.box('#menu [data-close]')
            self.assertEqual((round(close['x']), round(close['y'])), (x, round(side['y'])), hand)

    def test_menu_lists_the_chart_feedback_then_settings_and_about(self):
        self.loaded()
        self.page.click('#panel [data-menu]')
        self.assertEqual(self.shown(), 'Menu')
        self.assertEqual(self.page.locator('#menu').get_attribute('role'), 'dialog')
        self.assertEqual([n.strip() for n in self.page.locator('#menu .nss-menu-name').all_text_contents()],
                         ['Chart', '💡 Feedback & ideas', 'Settings', 'Guide', 'About'])
        self.assertEqual(self.page.locator('#menu [data-guide] .nss-menu-tag').text_content(), '4 STEPS')
        self.assertEqual(self.page.locator('#menu .nss-soon').count(), 0)
        self.assertEqual(self.page.locator('#menu [aria-disabled]').count(), 0)
        chart = self.page.locator('#menu [data-view="chart"]')
        self.assertEqual(chart.get_attribute('aria-current'), 'page')
        # Chart is where we are: choosing it closes the menu.
        chart.click()
        self.closed()

    # ---- Feedback --------------------------------------------------------------
    def feedback_server(self, status=204):
        """The feedback Worker, stood in for: what it was sent, and the answer given."""
        sent = []
        def answer(route):
            sent.append(route.request.post_data_json)
            route.fulfill(status=status)
        self.page.route('**/api/feedback', answer)
        return sent

    def test_feedback_is_sent_and_cleared(self):
        sent = self.feedback_server()
        self.loaded()
        self.page.click('#panel [data-menu]')
        send = self.page.locator('#feedback [type="submit"]')
        self.assertEqual(send.is_disabled(), True)                    # nothing to send yet
        self.page.fill('#fbText', '   ')
        self.assertEqual(send.is_disabled(), True)
        self.page.fill('#fbText', 'A spot list for Northumberland, please')
        send.click()
        self.page.wait_for_function("document.querySelector('#fbState').textContent === 'Thanks, sent.'")
        self.assertEqual(self.page.input_value('#fbText'), '')
        self.assertEqual(send.is_disabled(), True)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['text'], 'A spot list for Northumberland, please')
        self.assertEqual((sent[0]['lang'], sent[0]['surface'], sent[0]['v'], sent[0]['website']), ('en', 'browser', 'dev', ''))
        # The menu stays open, to see it went.
        self.assertEqual(self.shown(), 'Menu')

    def test_feedback_that_fails_stays_to_try_again(self):
        sent = self.feedback_server(status=502)
        self.loaded()
        self.page.click('#panel [data-menu]')
        self.page.fill('#fbText', 'Wind in knots')
        self.page.click('#feedback [type="submit"]')
        self.page.wait_for_function("document.querySelector('#fbState').textContent === \"Couldn't send. Try again.\"")
        self.assertEqual(self.page.input_value('#fbText'), 'Wind in knots')
        self.assertEqual(self.page.locator('#feedback [type="submit"]').is_disabled(), False)
        self.assertEqual(len(sent), 1)

    def test_feedback_in_the_language_chosen(self):
        self.new_page(service_workers='block', first_open=True, locale='de-DE')
        sent = self.feedback_server()
        self.loaded()
        self.page.keyboard.press('Escape')
        self.closed()
        self.page.click('#panel [data-menu]')
        self.assertEqual(self.page.locator('#feedback .nss-menu-name').text_content(), '💡 Feedback & Ideen')
        self.page.fill('#fbText', 'Danke!')
        self.page.click('#feedback [type="submit"]')
        self.page.wait_for_function("document.querySelector('#fbState').textContent === 'Danke, gesendet.'")
        self.assertEqual(sent[0]['lang'], 'de')

    def test_timeline_spans_the_panel_but_the_menu_button(self):
        self.loaded()
        tl, btn = self.box('#panel .nss-timeline'), self.box('#panel [data-menu]')
        self.assertEqual(round(tl['width']), 390 - 2 * 12 - 6 - 48)
        self.assertEqual(round(btn['x'] - (tl['x'] + tl['width'])), 6)

    def test_panel_setting_applies_at_once_and_is_remembered(self):
        self.loaded()
        self.page.click('#panel [data-menu]')
        self.page.click('[data-go="settings"]')
        self.assertEqual(self.shown(), 'Settings')
        sw = self.page.locator('[data-set="panel"]')
        self.assertEqual(sw.get_attribute('role'), 'group')
        self.assertEqual(self.page.locator('#' + sw.get_attribute('aria-labelledby')).text_content(), 'Panel')
        self.assertEqual(sw.locator('[data-value="bottom"]').get_attribute('aria-pressed'), 'true')
        sw.locator('[data-value="side"]').click()
        # Applied behind the sheet, which stays open.
        self.page.wait_for_function("document.querySelector('#panel').hasAttribute('data-away')")
        self.assertEqual(self.page.locator('#column').get_attribute('data-away'), None)
        self.assertEqual(self.shown(), 'Settings')
        self.assertEqual(sw.locator('[data-value="side"]').get_attribute('aria-pressed'), 'true')
        self.assertEqual(sw.locator('[data-value="bottom"]').get_attribute('aria-pressed'), 'false')
        self.page.reload()
        self.page.wait_for_function("document.querySelector('.nss-vtimeline').getAttribute('aria-valuemax') !== '0'")
        self.assertEqual(self.page.locator('#column').get_attribute('data-away'), None)
        self.assertEqual(self.page.locator('#panel').get_attribute('data-away'), '')
        self.assertEqual(self.shown(), None)
        self.setting('panel', 'bottom')
        self.page.wait_for_function("document.querySelector('#column').hasAttribute('data-away')")

    def test_hand_setting_moves_the_column_and_the_menu_button(self):
        self.loaded()
        self.setting('panel', 'side')
        self.page.wait_for_function("getComputedStyle(document.querySelector('#column')).opacity === '1'")
        self.assertEqual(round(self.box('#column')['x']), 390 - 64)
        self.assertEqual(self.page.locator('[data-set="hand"] [data-value="right"]').get_attribute('aria-pressed'), 'true')
        self.setting('hand', 'left')
        self.assertEqual(self.page.locator('html').get_attribute('data-hand'), 'left')
        self.assertEqual(round(self.box('#column')['x']), 0)
        self.assertEqual(self.page.locator('[data-set="hand"] [data-value="left"]').get_attribute('aria-pressed'), 'true')
        # The key comes out of the column towards the chart: to its right now.
        self.page.keyboard.press('Escape')
        self.closed()
        self.page.click('#column .nss-band[data-band="wind"]')
        self.page.wait_for_function("!document.querySelector('#flyout').getAnimations().length")
        self.assertGreaterEqual(self.box('#flyout')['x'], 64)
        self.page.reload()
        self.page.wait_for_function("document.querySelector('.nss-vtimeline').getAttribute('aria-valuemax') !== '0'")
        self.assertEqual(self.page.locator('html').get_attribute('data-hand'), 'left')
        self.assertEqual(round(self.box('#column')['x']), 0)
        # The open panel too: the menu button at the left end of the timeline row.
        self.setting('panel', 'bottom')
        self.page.wait_for_function("!document.querySelector('#panel').hasAttribute('data-away')")
        tl, btn = self.box('#panel .nss-timeline'), self.box('#panel [data-menu]')
        self.assertEqual(round(btn['x']), 12)
        self.assertGreater(tl['x'], btn['x'] + btn['width'])
        self.assertEqual(round(tl['width']), 390 - 2 * 12 - 6 - 48)

    def test_menu_leaves_the_time_band_and_map_alone(self):
        slider = self.loaded()
        self.page.wait_for_function(ALL_IN)
        slider.focus()
        self.page.keyboard.press('Home')
        self.page.keyboard.press('ArrowRight')
        self.page.click('#panel .nss-band[data-band="wind"]')
        before = (slider.get_attribute('aria-valuenow'), self.chart())
        self.page.click('#panel [data-menu]')
        self.page.click('[data-go="settings"]')
        self.page.click('#settings [data-back]')
        self.page.click('[data-go="about"]')
        self.page.click('#about [data-back]')
        self.page.click('#menu [data-close]')
        self.closed()
        self.assertEqual((slider.get_attribute('aria-valuenow'), self.chart()), before)
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="wind"]').get_attribute('aria-pressed'), 'true')

    def test_menu_by_keyboard_keeps_focus_and_gives_it_back(self):
        self.loaded()
        self.page.focus('#panel [data-menu]')
        self.page.keyboard.press('Enter')
        self.assertEqual(self.shown(), 'Menu')
        self.assertEqual(self.focused().startswith('Chart'), True)
        # Behind the menu nothing can be reached.
        for sel in ('#panel', '#column', '#chart'):
            self.assertEqual(self.page.evaluate(f"document.querySelector('{sel}').inert"), True, sel)
        inside = "!!document.activeElement.closest('#menu')"
        for _ in range(10):
            self.page.keyboard.press('Tab')
            self.assertEqual(self.page.evaluate(inside), True)
        self.page.focus('#menu .nss-menu-item[data-view="chart"]')
        self.page.keyboard.press('Shift+Tab')
        self.assertEqual(self.focused(), 'Close menu')
        self.page.keyboard.press('Tab')
        self.assertEqual(self.focused().startswith('Chart'), True)
        # Settings, and Back, by keyboard.
        self.page.focus('[data-go="settings"]')
        self.page.keyboard.press('Enter')
        self.assertEqual(self.shown(), 'Settings')
        self.assertEqual(self.focused(), 'Back to menu')
        for _ in range(6):
            self.page.keyboard.press('Tab')
            self.assertEqual(self.page.evaluate("!!document.activeElement.closest('#settings')"), True)
        self.page.focus('#settings [data-back]')
        self.page.keyboard.press('Enter')
        self.assertEqual(self.shown(), 'Menu')
        self.assertEqual(self.focused().startswith('Settings'), True)
        self.page.keyboard.press('Escape')
        self.closed()
        self.assertEqual(self.page.evaluate("document.activeElement === document.querySelector('#panel [data-menu]')"), True)
        self.assertEqual(self.page.evaluate("document.querySelector('#panel').inert || document.querySelector('#chart').inert"), False)

    def test_escape_from_settings_gives_focus_to_the_new_panel(self):
        self.loaded()
        self.setting('panel', 'side')
        self.page.keyboard.press('Escape')
        self.closed()
        self.assertEqual(self.page.evaluate("document.activeElement === document.querySelector('#column [data-menu]')"), True)

    def test_scrim_and_grip_close_the_menu(self):
        self.loaded()
        self.page.click('#panel [data-menu]')
        self.page.wait_for_function("getComputedStyle(document.querySelector('#menu')).transform === 'none'")
        self.page.mouse.click(195, 60)                               # the scrim, above the sheet
        self.closed()
        self.page.click('#panel [data-menu]')
        self.page.click('[data-go="about"]')
        self.assertEqual(self.shown(), 'About')
        self.assertIn('MET Norway', self.page.locator('#about').text_content())
        g = self.box('#about .nss-sheet-grip')
        x, y = g['x'] + g['width'] / 2, g['y'] + g['height'] / 2
        # A short pull springs back; a long one closes it.
        self.page.mouse.move(x, y); self.page.mouse.down(); self.page.mouse.move(x, y + 20, steps=4)
        self.page.wait_for_timeout(300); self.page.mouse.up()
        self.assertEqual(self.shown(), 'About')
        self.page.wait_for_function("getComputedStyle(document.querySelector('#about')).transform === 'none'")
        self.page.mouse.move(x, y); self.page.mouse.down(); self.page.mouse.move(x, y + 150, steps=6); self.page.mouse.up()
        self.closed()

    def test_menu_without_sliding_with_reduce_motion(self):
        self.new_page(service_workers='block', reduced_motion='reduce')
        self.loaded()
        self.page.click('#panel [data-menu]')
        self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('#menu')).transform"), 'none')
        self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('#menu')).transitionDuration"), '0s')
        self.page.keyboard.press('Escape')
        self.closed()

    # ---- Language ----------------------------------------------------------------
    def kept_lang(self):
        return self.page.evaluate("localStorage.getItem('nss.lang')")

    def test_first_open_asks_with_the_phone_language_picked(self):
        self.new_page(service_workers='block', first_open=True, locale='de-DE')
        self.loaded()
        self.assertEqual(self.shown(), 'Sprache')
        self.assertEqual(self.page.locator('html').get_attribute('lang'), 'de-DE')
        self.assertEqual(self.page.locator('[data-lang="de"]').get_attribute('aria-checked'), 'true')
        self.assertEqual(self.focused().startswith('Deutsch'), True)
        self.assertEqual(self.page.locator('#language [data-back]').is_hidden(), True)
        self.assertEqual(self.page.locator('#language [data-lang-lede]').is_visible(), True)
        self.assertEqual(self.page.locator('#language [data-lang]').count(), 6)
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="pressure"]').text_content(), 'Luftdruck')
        self.assertEqual(self.kept_lang(), None)
        # Picking another is the answer: in it at once, and kept.
        self.page.click('[data-lang="nl"]')
        self.closed()
        self.assertEqual(self.page.locator('html').get_attribute('lang'), 'nl-NL')
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="pressure"]').text_content(), 'Luchtdruk')
        self.assertEqual(self.page.locator('#panel [data-menu]').get_attribute('aria-label'), 'Menu')
        self.assertEqual(self.kept_lang(), '"nl"')
        self.page.reload()
        self.page.wait_for_function("document.querySelector('.nss-timeline').getAttribute('aria-valuemax') !== '0'")
        self.assertEqual(self.shown(), None)
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="wind"]').text_content(), 'Wind')
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="swell"]').text_content(), 'Deining')

    def test_first_open_closed_keeps_the_phone_language(self):
        self.new_page(service_workers='block', first_open=True, locale='nb-NO')
        self.loaded()
        self.assertEqual(self.shown(), 'Språk')
        self.page.keyboard.press('Escape')
        self.closed()
        self.assertEqual(self.kept_lang(), '"nb"')
        self.page.reload()
        self.page.wait_for_function("document.querySelector('.nss-timeline').getAttribute('aria-valuemax') !== '0'")
        self.assertEqual(self.shown(), None)
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="pressure"]').text_content(), 'Lufttrykk')
        # From Settings, the same sheet, now with its way back.
        self.page.click('#panel [data-menu]')
        self.page.click('[data-go="settings"]')
        self.page.click('[data-go="language"]')
        self.assertEqual(self.page.locator('#language [data-back]').is_visible(), True)
        self.assertEqual(self.page.locator('#language [data-lang-lede]').is_hidden(), True)

    def test_a_phone_in_another_language_gets_english(self):
        self.new_page(service_workers='block', first_open=True, locale='es-ES')
        self.loaded()
        self.assertEqual(self.shown(), 'Language')
        self.assertEqual(self.page.locator('[data-lang="en"]').get_attribute('aria-checked'), 'true')

    def test_language_setting_applies_at_once_and_is_remembered(self):
        self.loaded()
        self.page.click('#panel [data-menu]')
        self.page.click('[data-go="settings"]')
        self.assertEqual(self.page.locator('#settings [data-go="language"] [data-lang-name]').text_content(), 'English')
        self.page.click('[data-go="language"]')
        self.assertEqual(self.shown(), 'Language')
        self.assertEqual(self.page.locator('[data-lang="en"]').get_attribute('aria-checked'), 'true')
        self.page.click('[data-lang="fr"]')
        # Applied behind the sheet, which stays open, in French now.
        self.assertEqual(self.shown(), 'Langue')
        self.assertEqual(self.page.locator('[data-lang="fr"]').get_attribute('aria-checked'), 'true')
        self.assertEqual(self.page.locator('[data-lang="en"]').get_attribute('aria-checked'), 'false')
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="swell"]').text_content(), 'Houle')
        self.page.click('#language [data-back]')
        self.assertEqual(self.shown(), 'Réglages')
        self.assertEqual(self.focused().startswith('Langue'), True)
        self.assertEqual(self.page.locator('#settings [data-go="language"] [data-lang-name]').text_content(), 'Français')
        self.page.keyboard.press('Escape')
        self.closed()
        # The time, in French too.
        slider = self.page.locator('.nss-timeline')
        self.assertTrue(slider.get_attribute('aria-valuetext').split(' ')[0] in
                        ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'))
        self.page.reload()
        self.page.wait_for_function("document.querySelector('.nss-timeline').getAttribute('aria-valuemax') !== '0'")
        self.assertEqual(self.page.locator('html').get_attribute('lang'), 'fr-FR')
        self.assertEqual(self.page.locator('#panel .nss-band[data-band="pressure"]').text_content(), 'Pression')

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
        self.page.wait_for_function("document.querySelector('#rStatus').textContent.startsWith('Offline · ')")
        self.assertEqual(self.page.locator('.nss-timeline').get_attribute('aria-valuemax'), str(len(STEPS) - 1))
        self.page.wait_for_function("""(() => { const s = document.querySelector('.nss-timeline'),
            ticks = s.querySelectorAll('.nss-tick:not(.nss-tick--day):not(.nss-tick--now)');
            return !ticks[+s.getAttribute('aria-valuenow')].classList.contains('nss-tick--pending'); })()""")

    def test_debug_names_the_cell_tapped(self):
        # ?debug=1: a tap on the chart shows the cell under it (grid.js), its
        # own numbers from the run's cell tile, and the frame's node beside them.
        self.page.goto(f'{self.origin}/index.html?debug=1&frames={self.origin}/_frames/cells/')
        self.page.wait_for_function("document.querySelector('#rStatus').hidden")
        x, y = self.page.evaluate("""() => { const [x, y] = grid.lonLatToKm(-0.95, 54.8); view.x = x + 30; view.y = y; requestDraw();
            return [W / 2 + (x - view.x) * view.k, Hs / 2 - (y - view.y) * view.k]; }""")
        self.page.mouse.click(x, y)
        self.page.wait_for_function("[...document.querySelectorAll('pre')].some((p) => p.textContent.includes(' sea: Hs '))")
        text = self.page.locator('pre').last.text_content()
        self.assertIn('cell d4:219:-4 (54.75N 1.00W)', text)
        self.assertRegex(text, r'peak \d+\.\d s from \d+°, longest \d+\.\d s from \d+°')
        self.assertIn("frame's 25 km node", text)

    # ---- Play ---------------------------------------------------------------------
    def playing(self, panel='#panel'):
        return self.page.locator(f'{panel} [data-play]').get_attribute('aria-pressed') == 'true'

    def progress(self, panel='#panel'):
        return self.page.evaluate(f"document.querySelector('{panel} [data-progress]').style.getPropertyValue('--progress')")

    def at(self):
        return int(self.page.locator('.nss-timeline').get_attribute('aria-valuenow'))

    def from_the_start(self):
        slider = self.loaded()
        self.page.wait_for_function(ALL_IN)
        now = self.at()
        slider.focus()
        self.page.keyboard.press('Home')
        return now

    def test_play_runs_on_to_the_last_frame_and_stops(self):
        self.from_the_start()
        self.assertEqual(self.progress(), '0.00%')
        play = self.page.locator('#panel [data-play]')
        # Beside the slider, not in it, so a screen reader finds it.
        self.assertTrue(self.page.evaluate("[...document.querySelectorAll('[data-play]')].every((b) => !b.closest('[role=slider]'))"))
        self.assertEqual(play.get_attribute('aria-label'), 'Play through time')
        self.assertFalse(self.playing())
        start = time.monotonic()
        play.click()
        self.assertTrue(self.playing())
        self.assertEqual(play.get_attribute('aria-label'), 'Pause')
        self.page.wait_for_function("document.querySelector('#panel [data-play]').getAttribute('aria-pressed') === 'false'", timeout=10000)
        # About four frames a second.
        self.assertGreater(time.monotonic() - start, (len(STEPS) - 1) / 4 * 0.8)
        self.assertLess(time.monotonic() - start, (len(STEPS) - 1) / 4 * 1.6)
        self.assertEqual(self.at(), len(STEPS) - 1)
        self.assertEqual(self.page.locator('#panel [data-lead]').text_content(), f'+{STEPS[-1]}H')
        self.assertEqual(self.progress(), '100.00%')
        self.assertEqual(play.get_attribute('aria-label'), 'Play through time')
        # From the last frame, play does nothing.
        play.click()
        self.assertFalse(self.playing())

    def test_touching_the_timeline_pauses_play_for_good(self):
        now = self.from_the_start()
        self.page.click('#panel [data-play]')
        self.page.wait_for_function("+document.querySelector('.nss-timeline').getAttribute('aria-valuenow') >= 2")
        b = self.box('#panel .nss-timeline')
        self.page.mouse.click(b['x'] + b['width'] - 40, b['y'] + b['height'] / 2)
        self.assertFalse(self.playing())
        self.page.wait_for_timeout(300)
        at = self.at()
        self.assertEqual(self.progress(), f'{100 * at / (len(STEPS) - 1):.2f}%')
        self.page.wait_for_timeout(800)
        self.assertEqual(self.at(), at)
        # Play goes on from there.
        self.page.click('#panel [data-play]')
        self.page.wait_for_function(f"+document.querySelector('.nss-timeline').getAttribute('aria-valuenow') > {at}")
        self.assertTrue(self.playing())
        # A double-tap stops it and goes back to now.
        self.page.mouse.dblclick(b['x'] + 80, b['y'] + b['height'] / 2)
        self.assertFalse(self.playing())
        self.page.wait_for_function(f"document.querySelector('.nss-timeline').getAttribute('aria-valuenow') === '{now}'")
        self.page.wait_for_timeout(600)
        self.assertEqual(self.at(), now)

    def test_the_map_and_the_bands_dont_pause_play(self):
        self.from_the_start()
        self.page.click('#panel [data-play]')
        self.page.mouse.move(150, 200)
        self.page.mouse.down()
        self.page.mouse.move(100, 260, steps=4)
        self.page.mouse.up()
        self.page.mouse.wheel(0, -200)
        self.page.click('#panel .nss-band[data-band="swell"]')
        self.page.click('#panel [data-var="period"]')
        self.assertTrue(self.playing())
        self.page.click('#panel [data-play]')                      # the button pauses it
        self.assertFalse(self.playing())
        self.assertLess(self.at(), len(STEPS) - 1)

    def test_play_steps_frame_by_frame_with_reduce_motion(self):
        self.new_page(service_workers='block', reduced_motion='reduce')
        self.from_the_start()
        self.page.click('#panel [data-play]')
        seen = self.page.evaluate("""() => new Promise((r) => { const out = [], t0 = performance.now();
            (function f() { out.push(document.querySelector('#panel [data-track]').style.transform);
              if (performance.now() - t0 < 1500) requestAnimationFrame(f); else r(out); })(); })""")
        at = [float(re.search(r'-?[\d.]+', t).group()) for t in seen]
        self.assertGreater(len(set(at)), 3)
        self.assertTrue(all(a % 8 == 0 for a in at), sorted(set(at)))

    def test_docked_play_at_the_foot_and_progress_up_the_chart_side(self):
        for hand in ('right', 'left'):
            with self.subTest(hand=hand):
                self.new_page(service_workers='block')
                self.kept(**{'nss.docked': True, 'nss.hand': hand})
                self.loaded()
                self.page.wait_for_function("getComputedStyle(document.querySelector('#column')).opacity === '1'")
                col, tl, play = self.box('#column'), self.box('.nss-vtimebox'), self.box('#column [data-play]')
                line = self.box('#column [data-progress]')
                # To the column's edge on the chart's side, inset from the screen's.
                if hand == 'right':
                    self.assertEqual(round(tl['x']), round(col['x']))
                    self.assertEqual(round(tl['x'] + tl['width']), 390 - 12)
                    self.assertEqual(round(line['x']), round(tl['x']))
                else:
                    self.assertEqual(round(tl['x']), 12)
                    self.assertEqual(round(tl['x'] + tl['width']), round(col['x'] + col['width']))
                    self.assertEqual(round(line['x'] + line['width']), round(tl['x'] + tl['width']))
                self.assertEqual(round(line['width']), 2)
                # Play: the full width at the foot; the line runs from it upward.
                self.assertEqual(round(play['width']), round(tl['width']) - 1)
                self.assertEqual(round(play['height']), 44)
                self.assertEqual(round(play['y'] + play['height']), round(tl['y'] + tl['height']) - 1)
                self.assertEqual(round(line['y'] + line['height']), round(play['y']))
                vt = self.page.locator('.nss-vtimeline')
                vt.focus()
                self.page.keyboard.press('Home')
                fill = "document.querySelector('#column [data-progress] i').getBoundingClientRect()"
                self.assertEqual(self.page.evaluate(fill + '.height'), 0)
                self.page.keyboard.press('End')
                self.assertEqual(round(self.page.evaluate(fill + '.height')), round(line['height']))
                self.assertEqual(round(self.page.evaluate(fill + '.bottom')), round(play['y']))      # filled upward from the button
                self.page.click('#column [data-play]')                  # from the last frame: nothing
                self.assertFalse(self.playing('#column'))
                vt.focus()
                self.page.keyboard.press('Home')
                self.page.click('#column [data-play]')
                self.assertTrue(self.playing('#column'))
                self.page.wait_for_function("+document.querySelector('.nss-vtimeline').getAttribute('aria-valuenow') >= 1")

    def test_says_when_the_run_was_published(self):
        # With nothing else to say, a quiet line says when the run was published.
        self.loaded()
        made = self.page.locator('#rMade')
        self.page.wait_for_function("!document.querySelector('#rMade').hidden")
        self.assertRegex(made.text_content(), r'^Updated (\w+ )?\d\d:\d\d$')

    def test_no_manifest_says_offline(self):
        self.open('empty')
        self.page.wait_for_function("document.querySelector('#rStatus').textContent === 'Offline'")


if __name__ == '__main__':
    unittest.main()
