# Notes for Claude

- Pull requests: fill in `.github/pull_request_template.md` and no more. One line on what changed; no sections, test lists or caveats. The owner doesn't read PR descriptions.
- Chart numbers are NOAA's. Wetterzentrale is for looking at by hand only: never fetched, kept or uploaded by a workflow, and never in the app or on a data branch (tests/test_validate.py checks).
- Open the PR when the work is pushed; don't ask first.
- Words in the app go in all six languages in i18n.js (en, nb, da, de, nl, fr), never English alone, and must fit on a phone in the longest of them. tests/test_i18n.py checks every language has every key.
