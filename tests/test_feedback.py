"""The feedback Worker (feedback/worker.mjs), under Node, with Cloudflare's
email binding stood in for (feedback_worker.mjs): what it emails, and what it
turns away (other sites, nothing or too much to say, bots, a binding that
fails). The email is read back with Python's own email parser.
"""
import email
import email.policy
import json
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = 'https://northsea.surf'


@unittest.skipIf(shutil.which('node') is None and not os.environ.get('CI'), 'needs Node')
class Worker(unittest.TestCase):
    def run_worker(self, *requests):
        out = subprocess.run(['node', os.path.join(HERE, 'feedback_worker.mjs')], input=json.dumps(requests),
                             capture_output=True, text=True, check=True, timeout=60)
        return json.loads(out.stdout)

    def post(self, body, origin=SITE, **kw):
        return dict(body=json.dumps(body), origin=origin, **kw)

    def test_emails_the_feedback(self):
        text = 'Dønninger i Nordsjøen: could the swell key go to 8 m?\nThanks'
        [r] = self.run_worker(self.post(dict(text=f'  {text}  ', website='', lang='nb', surface='standalone', v='abc123')))
        self.assertEqual(r['status'], 204)
        [m] = r['sent']
        self.assertEqual((m['from'], m['to']), ('feedback@northsea.surf', 'matt@example.com'))
        msg = email.message_from_string(m['raw'], policy=email.policy.default)
        self.assertEqual(msg['Subject'], 'North Sea Surf feedback')
        self.assertEqual(msg['To'], 'matt@example.com')
        self.assertTrue(msg['Message-ID'].endswith('@northsea.surf>'))
        self.assertIsNotNone(msg['Date'].datetime)
        body = msg.get_content()
        self.assertTrue(body.startswith(text + '\n\n--\n'), body)
        for line in ('site: northsea.surf', 'language: nb', 'open: standalone', 'version: abc123'):
            self.assertIn(line, body)
        self.assertTrue(all(len(l) <= 78 for l in m['raw'].split('\r\n')))

    def test_staging_too(self):
        [r] = self.run_worker(self.post(dict(text='hi'), origin='https://staging.northsea.surf'))
        self.assertEqual((r['status'], len(r['sent'])), (204, 1))

    def test_turned_away(self):
        long = 'x' * 2001
        rs = self.run_worker(
            self.post(dict(text='hi'), origin='https://example.com'),     # another site
            self.post(dict(text='hi'), origin=None),                      # no site at all
            self.post(dict(text='   ')),                                  # nothing to say
            self.post(dict(text=long)),                                   # too much
            self.post(dict(text=['hi'])),                                 # not text
            dict(body='not json', origin=SITE),
            dict(method='GET', origin=SITE),
        )
        self.assertEqual([r['status'] for r in rs], [403, 403, 400, 400, 400, 400, 405])
        self.assertEqual(sum(len(r['sent']) for r in rs), 0)

    def test_a_bot_is_thanked_and_dropped(self):
        [r] = self.run_worker(self.post(dict(text='Cheap pills', website='http://spam.example')))
        self.assertEqual((r['status'], r['sent']), (204, []))

    def test_what_the_app_says_about_itself_is_kept_short_and_plain(self):
        [r] = self.run_worker(self.post(dict(text='hi', lang='en\r\nBcc: someone@example.com', surface='x' * 200)))
        msg = email.message_from_string(r['sent'][0]['raw'], policy=email.policy.default)
        self.assertIsNone(msg['Bcc'])
        body = msg.get_content()
        self.assertIn('language: enBcc: someoneexample.com', body)
        self.assertIn('open: ' + 'x' * 40 + '\n', body)

    def test_a_failed_send_says_so(self):
        [r] = self.run_worker(self.post(dict(text='hi'), mailFails=True))
        self.assertEqual(r['status'], 502)


if __name__ == '__main__':
    unittest.main()
