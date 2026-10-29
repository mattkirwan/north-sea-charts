"""The chart app in a browser (Chromium, by Playwright): index.html and app.js
as served, reading a made-up run published the way chart_frames.py publishes
one (manifest.json and gzipped frames, encoded by its own encode()), from a
local server. It opens on the frame nearest now and draws it, the timeline
moves the forecast on, the bands switch and are remembered, the menu opens
and closes as a sheet (keyboard, scrim, grip) with feedback, and the panel
and hand settings, in it, and without a manifest it says it's offline. On first open it
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
                         ['Chart', '💡 Feedback & ideas', 'Settings', 'About'])
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
        self.page.wait_for_function("document.querySelector('#rStatus').textContent.startsWith('Offline · run')")
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

    def test_no_manifest_says_offline(self):
        self.open('empty')
        self.page.wait_for_function("document.querySelector('#rStatus').textContent === 'Offline'")


if __name__ == '__main__':
    unittest.main()
