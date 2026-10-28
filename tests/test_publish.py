"""Publishing the chart app's frames: which frames a run publishes and when a
partial run is tried again (chart_frames.to_publish, published.py), and the
copy to Cloudflare R2 (publish-r2.sh), against a stand-in S3 server (moto)
when the AWS CLI and moto are installed."""
import gzip
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import chart_frames as cf  # noqa: E402
import published  # noqa: E402


class ToPublish(unittest.TestCase):
    steps = list(range(10))

    def test_whole_run(self):
        self.assertEqual(cf.to_publish(self.steps, set(self.steps)), self.steps)

    def test_stops_at_the_first_gap(self):
        self.assertEqual(cf.to_publish(self.steps, set(self.steps) - {7, 9}), self.steps[:7])

    def test_too_short_is_refused(self):
        with self.assertRaises(SystemExit):
            cf.to_publish(self.steps, set(self.steps) - {5})

    def test_retry_that_does_no_better_publishes_nothing(self):
        self.assertIsNone(cf.to_publish(self.steps, set(self.steps) - {7}, had=7))

    def test_retry_that_does_better(self):
        self.assertEqual(cf.to_publish(self.steps, set(self.steps) - {9}, had=7), self.steps[:9])


class Published(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(published.label(None), '')
        self.assertEqual(published.label({'runLabel': '2026-10-27 12z'}), '2026-10-27 12z')  # before 'complete'
        self.assertEqual(published.label({'runLabel': '2026-10-27 12z', 'complete': True}), '2026-10-27 12z')
        self.assertEqual(published.label({'runLabel': '2026-10-27 12z', 'complete': False}), '2026-10-27 12z partial')


def _have_r2_tools():
    if not shutil.which('aws'):
        return False
    try:
        import boto3  # noqa: F401
        from moto.server import ThreadedMotoServer  # noqa: F401
        return True
    except ImportError:
        return False


def public_domain(port, bucket):
    """R2's public domain, played by a local server: the bucket's objects by
    their keys, with a CORS header, or 403 for every request while not live."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import boto3
    s3 = boto3.client('s3', endpoint_url=f'http://127.0.0.1:{port}', region_name='us-east-1',
                      aws_access_key_id='test', aws_secret_access_key='test')

    class Domain(BaseHTTPRequestHandler):
        def do_GET(self):
            key = self.path.lstrip('/').split('?')[0]
            try:
                assert self.server.live
                body = s3.get_object(Bucket=bucket, Key=key)['Body'].read()
            except Exception:
                self.send_response(403)
                self.end_headers()
                return
            self.send_response(200)
            if self.server.cors and self.headers.get('Origin'):
                self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Domain)
    srv.live = srv.cors = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@unittest.skipUnless(_have_r2_tools(), 'needs the AWS CLI and moto[server]')
class PublishR2(unittest.TestCase):
    BUCKET = 'frames'
    ORIGIN = 'https://app.example.test'
    RUN = '2026-10-27-12z'

    @classmethod
    def setUpClass(cls):
        from moto.server import ThreadedMotoServer
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            cls.port = s.getsockname()[1]
        cls.server = ThreadedMotoServer(ip_address='127.0.0.1', port=cls.port)
        cls.server.start()

        cls.domain = public_domain(cls.port, cls.BUCKET)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.domain.shutdown()

    def setUp(self):
        import boto3
        self.endpoint = f'http://127.0.0.1:{self.port}'
        self.public = f'http://127.0.0.1:{self.domain.server_port}'
        self.domain.live, self.domain.cors = True, True
        self.s3 = boto3.client('s3', endpoint_url=self.endpoint, region_name='us-east-1',
                               aws_access_key_id='test', aws_secret_access_key='test')
        for o in self.s3.list_objects_v2(Bucket=self.BUCKET).get('Contents', []) if self.bucket_exists() else []:
            self.s3.delete_object(Bucket=self.BUCKET, Key=o['Key'])
        if not self.bucket_exists():
            self.s3.create_bucket(Bucket=self.BUCKET)
        # Three older runs and something that isn't a run, already on R2.
        for key in ('2026-10-26-18z/f000.bin.gz', '2026-10-27-00z/f000.bin.gz', '2026-10-27-06z/f000.bin.gz', 'notes/readme.txt'):
            self.s3.put_object(Bucket=self.BUCKET, Key=key, Body=b'old')
        self.out = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.out, self.RUN))
        for step in (0, 1, 384):
            with open(os.path.join(self.out, self.RUN, f'f{step:03d}.bin.gz'), 'wb') as f:
                f.write(gzip.compress(b'frame'))
        with open(os.path.join(self.out, 'manifest.json'), 'w') as f:
            json.dump(dict(runLabel='2026-10-27 12z', dir=self.RUN, steps=[0, 1, 384]), f)

    def tearDown(self):
        shutil.rmtree(self.out)

    def bucket_exists(self):
        return any(b['Name'] == self.BUCKET for b in self.s3.list_buckets()['Buckets'])

    def publish(self, **env):
        e = {**os.environ, 'R2_ENDPOINT': self.endpoint, 'R2_PUBLIC_URL': self.public, 'R2_ACCOUNT_ID': 'x',
             'APP_ORIGIN': self.ORIGIN,
             'R2_BUCKET': self.BUCKET, 'R2_ACCESS_KEY_ID': 'test', 'R2_SECRET_ACCESS_KEY': 'test', **env}
        return subprocess.run(['sh', os.path.join(ROOT, 'scripts', 'publish-r2.sh'), self.out], env=e,
                              capture_output=True, text=True)

    def local_manifest(self):
        with open(os.path.join(self.out, 'manifest.json')) as f:
            return json.load(f)

    def keys(self):
        return sorted(o['Key'] for o in self.s3.list_objects_v2(Bucket=self.BUCKET)['Contents'])

    def test_frames_then_manifest_then_older_runs_go(self):
        r = self.publish()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.keys(), ['2026-10-27-06z/f000.bin.gz', f'{self.RUN}/f000.bin.gz', f'{self.RUN}/f001.bin.gz',
                                       f'{self.RUN}/f384.bin.gz', 'manifest.json', 'notes/readme.txt'])
        frame = self.s3.get_object(Bucket=self.BUCKET, Key=f'{self.RUN}/f001.bin.gz')
        self.assertEqual(gzip.decompress(frame['Body'].read()), b'frame')
        self.assertEqual(frame['ContentType'], 'application/octet-stream')
        self.assertIn('immutable', frame['CacheControl'])
        self.assertNotIn('ContentEncoding', frame)
        self.assertEqual(self.local_manifest()['base'], self.public + '/')
        on_r2 = self.s3.get_object(Bucket=self.BUCKET, Key='manifest.json')
        self.assertEqual(json.load(on_r2['Body'])['base'], self.public + '/')
        self.assertEqual(on_r2['CacheControl'], 'public, max-age=60')

    def check_left_on_the_branch(self, r, why):
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(why, r.stdout)
        self.assertNotIn('base', self.local_manifest())
        self.assertNotIn('manifest.json', self.keys())

    def test_public_address_not_live(self):
        # As frames.northsea.surf did on 28 Oct: uploads work, the domain answers 403.
        self.domain.live = False
        self.check_left_on_the_branch(self.publish(), 'answers')

    def test_public_address_unreachable(self):
        self.check_left_on_the_branch(self.publish(R2_PUBLIC_URL='http://127.0.0.1:9'), "can't be reached")

    def test_no_cors_policy(self):
        self.domain.cors = False
        self.check_left_on_the_branch(self.publish(), 'no CORS header')

    def test_not_set_up(self):
        r = self.publish(R2_PUBLIC_URL='')
        self.assertEqual(r.returncode, 0)
        self.assertIn('not set up', r.stdout)
        self.assertNotIn('base', self.local_manifest())

    def test_nothing_to_publish(self):
        os.unlink(os.path.join(self.out, 'manifest.json'))
        r = self.publish()
        self.assertEqual(r.returncode, 0)
        self.assertIn('Nothing new', r.stdout)

    def test_failure_leaves_the_branch_on_its_own_frames(self):
        r = self.publish(R2_BUCKET='no-such-bucket')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('base', self.local_manifest())


if __name__ == '__main__':
    unittest.main()
