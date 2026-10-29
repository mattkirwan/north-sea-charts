#!/bin/sh
# Copy a run's frames (the folder given, as chart_frames.py wrote it) to
# Cloudflare R2, which phones download them from, and point the manifest
# there (its base) for publish-charts.sh to put on the frames branch. Run by
# frames.yml before the branch is published, so the manifest only names R2
# once the frames are on it; without R2 set up, or if this fails, the
# manifest has no base and phones take the frames from the branch, as before.
#
# Frames are kept a year in caches (a run's folder never changes); this run
# and the one before stay on R2, so a phone still on the last manifest
# finishes its frames; older runs are deleted. The cell tiles (cells/) are
# kept for good: the cells' history.
#
# Needs R2_PUBLIC_URL (where the bucket is served, e.g.
# https://frames.northsea.surf/), R2_ACCOUNT_ID, R2_BUCKET,
# R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY; R2_ENDPOINT overrides the S3
# address (for testing), APP_ORIGIN the app's (default https://northsea.surf).
# The bucket's CORS policy must let the app's pages GET from it, staging's too:
#   [{"AllowedOrigins": ["https://northsea.surf", "https://staging.northsea.surf"],
#     "AllowedMethods": ["GET"], "MaxAgeSeconds": 86400}]
set -e
cd "$1" 2>/dev/null && [ -f manifest.json ] || { echo 'Nothing new to publish'; exit 0; }
[ -n "$R2_PUBLIC_URL" ] || { echo 'R2 not set up (no R2_PUBLIC_URL); frames from the branch only'; exit 0; }
case "$R2_PUBLIC_URL" in */) ;; *) R2_PUBLIC_URL="$R2_PUBLIC_URL/" ;; esac
dir=$(python3 -c 'import json; print(json.load(open("manifest.json"))["dir"])')
[ -d "$dir" ] || { echo "No folder $dir"; exit 1; }

export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" AWS_DEFAULT_REGION=auto
# Newer AWS CLIs send checksums R2 may refuse; only when a call needs them.
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
s3() { aws s3 --endpoint-url "${R2_ENDPOINT:-https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com}" "$@"; }

# octet-stream, not gzip: the app unpacks the frames itself, and nothing on the
# way should unpack (or repack) them.
s3 cp --only-show-errors --recursive "$dir" "s3://$R2_BUCKET/$dir" \
  --cache-control 'public, max-age=31536000, immutable' --content-type application/octet-stream
echo "Frames on R2: $R2_PUBLIC_URL$dir/ ($(ls "$dir" | wc -l) files)"
# The run's cell tiles (cells/<run>/<steps>/, grid.py), if it has them. Kept
# for good, run after run: the deleting below is only of the run folders at
# the top of the bucket.
if [ -d cells ]; then
  s3 cp --only-show-errors --recursive cells "s3://$R2_BUCKET/cells" \
    --cache-control 'public, max-age=31536000, immutable' --content-type application/octet-stream
  echo "Cell tiles on R2: $(find cells -type f | wc -l) files"
fi

# Only point phones at R2 once a phone could read a frame there: a 200 from
# the public address, with the CORS header the app's page needs. (An address
# not yet live answers 403, and every phone would be left without frames.)
url="$R2_PUBLIC_URL$dir/$(ls "$dir" | head -1)"
head=$(curl -sS -o /dev/null -D - --max-time 30 -H "Origin: ${APP_ORIGIN:-https://northsea.surf}" "$url") \
  || { echo "R2's public address can't be reached; frames from the branch only"; exit 1; }
status=$(echo "$head" | head -1 | tr -d '\r')
case "$status" in *" 200"*) ;; *) echo "R2's public address answers \"$status\"; frames from the branch only"; exit 1 ;; esac
echo "$head" | grep -qi '^access-control-allow-origin:' \
  || { echo "R2 sends no CORS header to ${APP_ORIGIN:-https://northsea.surf}; set the bucket's CORS policy. Frames from the branch only"; exit 1; }

BASE="$R2_PUBLIC_URL" python3 -c '
import json, os
m = json.load(open("manifest.json"))
m["base"] = os.environ["BASE"]
json.dump(m, open("manifest.json", "w"), separators=(",", ":"))'
s3 cp --only-show-errors manifest.json "s3://$R2_BUCKET/manifest.json" --cache-control 'public, max-age=60' --content-type application/json

# This run and the one before stay; run folders are named by date, so they
# sort. Listed on its own line so a failed listing stops the script.
listing=$(s3 ls "s3://$R2_BUCKET/")
for old in $(echo "$listing" | awk '$1 == "PRE" { sub("/$", "", $2); print $2 }' \
             | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2}z$' | sort | head -n -2); do
  s3 rm --only-show-errors --recursive "s3://$R2_BUCKET/$old/"
  echo "Deleted $old from R2"
done
