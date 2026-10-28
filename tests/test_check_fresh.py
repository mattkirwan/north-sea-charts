"""The hourly freshness check (scripts/check_fresh.py), against made-up
branches: what it finds wrong, and that it finds nothing on a good one."""
import gzip
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
import check_fresh as cfr  # noqa: E402

H = 3600e3
NOW = 1793124000000  # 2026-10-27 18z
BASE = 'https://example.test/frames/'
R2 = 'https://r2.example.test/'
P, S = 4, 5
FRAME = gzip.compress(bytes(4 * P * P + 2 * S * S))


def branch(made_h_ago=3, run_h_ago=8, steps=(0, 1, 384), dir='2026-10-27-10z', frames=None, manifest=True, base=None):
    m = dict(run=NOW - run_h_ago * H, runLabel='2026-10-27 10z', made=NOW - made_h_ago * H, steps=list(steps),
             pad=3, grids=dict(p=P, s=S))
    if dir:
        m['dir'] = dir
    if base:
        m['base'] = base
    files = {f"{dir + '/' if dir else ''}f{s:03d}.bin.gz": FRAME for s in steps}
    files.update(frames or {})

    def fetch(url):
        # The manifest is always on the branch; the frames where base says.
        if url.startswith(BASE + 'manifest.json'):
            if manifest:
                return json.dumps(m).encode()
            raise OSError('HTTP 404 manifest.json')
        if not url.startswith(base or BASE):
            raise OSError(f'HTTP 404 {url}')
        name = url[len(base or BASE):].split('?')[0]
        if files.get(name) is None:
            raise OSError(f'HTTP 404 {name}')
        return files[name]
    return fetch


class Fresh(unittest.TestCase):
    def found(self, **kw):
        return cfr.problems(BASE, NOW, branch(**kw))

    def test_good_branch(self):
        self.assertEqual(self.found(), [])

    def test_old_layout_without_a_run_folder(self):
        self.assertEqual(self.found(dir=None), [])

    def test_frames_on_r2(self):
        self.assertEqual(self.found(base=R2), [])

    def test_stale(self):
        [p] = self.found(made_h_ago=cfr.MAX_AGE_H + 1)
        self.assertIn('last published 10 h ago', p)

    def test_no_manifest(self):
        [p] = self.found(manifest=False)
        self.assertIn('No manifest', p)

    def test_missing_frame(self):
        [p] = self.found(frames={'2026-10-27-10z/f384.bin.gz': None})
        self.assertIn('+384 h unreadable', p)

    def test_truncated_frame(self):
        [p] = self.found(frames={'2026-10-27-10z/f000.bin.gz': gzip.compress(b'short')})
        self.assertIn('+0 h is 5 bytes', p)

    def test_corrupt_frame(self):
        [p] = self.found(frames={'2026-10-27-10z/f000.bin.gz': b'not gzip'})
        self.assertIn('+0 h unreadable', p)

    def test_whole_run_in_the_past(self):
        found = self.found(made_h_ago=1, steps=(0, 1, 2))
        self.assertTrue(any('in the past' in p for p in found))



class AsTheAppAsks(unittest.TestCase):
    """get() asks as the app does, and refuses what a phone couldn't read."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Domain(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.seen = dict(self.headers)
                # Like Cloudflare's bot protection: Python's own client is refused.
                if self.headers.get('User-Agent', '').startswith('Python-urllib'):
                    self.send_response(403)
                    self.end_headers()
                    return
                self.send_response(200)
                if self.path.startswith('/cors'):
                    self.send_header('Access-Control-Allow-Origin', self.headers.get('Origin', '*'))
                self.end_headers()
                self.wfile.write(b'frame')

            def log_message(self, *a):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Domain)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_readable(self):
        self.assertEqual(cfr.get(self.url + '/cors/f000.bin.gz'), b'frame')
        self.assertEqual(self.seen['Origin'], cfr.ORIGIN)

    def test_no_cors_header(self):
        with self.assertRaisesRegex(OSError, 'no CORS header'):
            cfr.get(self.url + '/plain/f000.bin.gz')


if __name__ == '__main__':
    unittest.main()
