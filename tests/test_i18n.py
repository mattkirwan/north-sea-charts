"""The app's words (i18n.js) in every language: each language has every key
English has, and no others, with the same {names} to fill in; and every key
the page (data-t, data-t-label) and the scripts (tr('...')) ask for is there.
English falls back in the app, but nothing should be left to fall back.

  python -m unittest discover -s tests
"""
import json
import os
import re
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')


def read(name):
    with open(os.path.join(ROOT, name), encoding='utf-8') as f:
        return f.read()


LANGS = json.loads(subprocess.run(
    ['node', '-e', 'process.stdout.write(JSON.stringify(eval(require("fs").readFileSync(process.argv[1], "utf8") + ";LANGS")))',
     os.path.join(ROOT, 'i18n.js')], capture_output=True, text=True, check=True).stdout)
names = lambda s: sorted(re.findall(r'\{(\w+)\}', s))


class Words(unittest.TestCase):
    def test_every_language_has_every_key(self):
        en = LANGS['en']['t']
        for code, lang in LANGS.items():
            with self.subTest(lang=code):
                self.assertEqual(sorted(lang['t']), sorted(en))
                for k, s in lang['t'].items():
                    self.assertEqual(names(s), names(en[k]), f'{code}.{k}')

    def test_every_key_asked_for_is_there(self):
        asked = set(re.findall(r'data-t(?:-label)?="(\w+)"', read('index.html')))
        for name in ('app.js', 'hints.js'):
            asked |= set(re.findall(r"\btr\('(\w+)'", read(name)))
        self.assertEqual(sorted(asked - set(LANGS['en']['t'])), [])


if __name__ == '__main__':
    unittest.main()
