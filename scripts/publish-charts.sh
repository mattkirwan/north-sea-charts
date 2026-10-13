#!/bin/sh
# Publish the drawn charts (the folder given) as the single commit on BRANCH,
# replacing what was there, so the repo doesn't grow. Run by charts.yml after
# each pass.
set -e
cd "$1" 2>/dev/null && [ -f manifest.json ] || { echo 'Nothing new to publish'; exit 0; }
rm -rf .git
git init -q -b "$BRANCH"
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git add -A
git commit -q -m "GFS charts $(python3 -c 'import json; m = json.load(open("manifest.json")); print(m["runLabel"], "to +%dh" % m["steps"][-1])')"
git push -q -f "https://x-access-token:${TOKEN}@github.com/${GITHUB_REPOSITORY}.git" "$BRANCH"
