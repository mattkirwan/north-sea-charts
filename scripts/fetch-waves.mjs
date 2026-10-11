// Collects the latest measured waves around the North Sea and writes them as
// JSON to the path given as the first argument. Run every half hour by
// .github/workflows/waves.yml; the app reads the result.
//
// Source: NOAA's National Data Buoy Center, which relays the newest report
// from buoys and platforms worldwide, including North Sea oil and gas
// platforms on the WMO network, in one text file (latest_obs.txt).
// EMODnet Physics was tried first, but its ERDDAP servers hold no
// near-real-time wave collections.
import { writeFileSync } from 'node:fs';

const BOX = { s: 53.5, n: 75, w: -12, e: 32 };
const HOURS = 6; // older readings than this aren't "latest"

const get = async (u) => {
  const r = await fetch(u, { signal: AbortSignal.timeout(60e3) });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${u}`);
  return r.text();
};
const unescape = (s) => s.replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

// latest_obs.txt: one line per station with its newest report. Columns:
// STN LAT LON YYYY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD ...; "MM" is
// missing. Station names come from activestations.xml.
const [txt, xml] = await Promise.all([
  get('https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt'),
  get('https://www.ndbc.noaa.gov/activestations.xml').catch(() => '')
]);
const names = {};
for (const m of xml.matchAll(/<station\s[^>]*id="([^"]+)"[^>]*name="([^"]*)"/g)) names[m[1].toUpperCase()] = unescape(m[2]).trim();
const lines = txt.split('\n'), head = lines[0].replace(/^#/, '').trim().split(/\s+/);
const col = (n) => head.indexOf(n);
console.log(`NDBC: ${lines.length - 2} stations worldwide`);

const stations = [];
for (const line of lines.slice(2)) {
  const f = line.trim().split(/\s+/);
  if (f.length < head.length) continue;
  const num = (n) => (f[col(n)] === 'MM' ? null : +f[col(n)]);
  const lat = num('LAT'), lon = num('LON'), h = num('WVHT');
  if (lat == null || lat < BOX.s || lat > BOX.n || lon < BOX.w || lon > BOX.e) continue;
  const id = f[col('STN')], name = names[id.toUpperCase()] || `Station ${id}`;
  const ms = Date.UTC(+f[col('YYYY')], +f[col('MM')] - 1, +f[col('DD')], +f[col('hh')], +f[col('mm')]);
  const p = num('DPD') ?? num('APD'), d = num('MWD');
  console.log(`  ${id} ${name} ${lat},${lon} waves=${h ?? '-'} m period=${p ?? '-'} s dir=${d ?? '-'} ${new Date(ms).toISOString()}`);
  if (h == null || Date.now() - ms > HOURS * 3600e3) continue;
  stations.push({ name: name.replace(/\s+AWS$/, ''), code: id, lat, lon, ms, h, p, d });
}
console.log(`${stations.length} with a wave height in the last ${HOURS} h`);
writeFileSync(process.argv[2] || 'waves.json', JSON.stringify({ at: Date.now(), source: 'NOAA NDBC', hours: HOURS, stations }));
