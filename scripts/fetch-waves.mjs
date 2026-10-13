// Collects the latest measured waves around the North Sea and writes them as
// JSON to the path given as the first argument. Run every half hour by
// .github/workflows/waves.yml; the app reads the result.
//
// Sources:
// - The National Network of Regional Coastal Monitoring Programmes (CCO API):
//   wave buoys round the English coast, including Whitby, with height, peak
//   period and direction. The key (issued for mattkirwan.github.io) comes
//   from the CCO_API_KEY repository secret.
// - NOAA's National Data Buoy Center, which relays the newest report from
//   buoys and platforms worldwide, including North Sea oil and gas platforms
//   (height only) on the WMO network, in one text file (latest_obs.txt), and
//   keeps each station's last 45 days (realtime2/<id>.txt).
// Every station gets its last 48 hours (hist): from the source where it has
// one, and from what we published last time, plus this reading. So the app
// can follow a swell down the North Sea, platform by platform.
// EMODnet Physics was tried first, but its ERDDAP servers hold no
// near-real-time wave collections.
import { writeFileSync } from 'node:fs';

const BOX = { s: 53.5, n: 75, w: -12, e: 32 };
const HOURS = 6; // older readings than this aren't "latest"
const KEEP = 48 * 3600e3; // how far back each station's history goes
const REPO = process.env.GITHUB_REPOSITORY || 'mattkirwan/north-sea-charts';
const CCO_KEY = process.env.CCO_API_KEY || '';
if (!CCO_KEY) console.log('No CCO_API_KEY secret: skipping the Coastal Monitoring buoys');

const get = async (u) => {
  // The CCO API picks its format from Accept (it sends XML otherwise).
  const r = await fetch(u, { headers: { Referer: 'https://mattkirwan.github.io/', Accept: 'application/json, text/plain, */*' }, signal: AbortSignal.timeout(60e3) });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${u.replace(/key=[^&]+/, "key=***")}`);
  return r.text();
};
const unescape = (s) => s.replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

const stations = [];
const fresh = (ms) => ms && Date.now() - ms <= HOURS * 3600e3;
// The box reaches the west coast below Scotland (Morecambe Bay, Cleveleys);
// those buoys are in the Irish Sea and say nothing about North Sea swell.
const irishSea = (lat, lon) => lat < 55.8 && lon < -2.2;

// CCO: GeoJSON of every buoy's latest reading. Dates are "YYYYMMDD#HHMMSS" UTC;
// hs is significant height (m), tp peak period (s), pdir peak direction (deg from),
// hmax the biggest single wave (m), tz mean period (s), spread the directional
// spread (deg) and sst the sea temperature (C). One set of figures per buoy:
// the feed has no separate swell and wind-sea partitions.
if (CCO_KEY) try {
  const geo = JSON.parse(await get(`https://coastalmonitoring.org/observations/waves/latest?key=${CCO_KEY}&format=json`));
  const n = (v) => (v == null || v === '' ? null : +v);
  for (const f of geo.features || []) {
    const p = f.properties || {}, [lon, lat] = (f.geometry && f.geometry.coordinates) || [];
    const m = /^(\d{4})(\d\d)(\d\d)#(\d\d)(\d\d)/.exec(p.date || '');
    const ms = m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : 0;
    if (lat == null || lat < BOX.s || lat > BOX.n || lon < BOX.w || lon > BOX.e || irishSea(lat, lon)) continue;
    console.log(`  CCO ${p.sensor} ${lat},${lon} waves=${p.hs ?? '-'} m period=${p.tp ?? '-'} s dir=${p.pdir ?? '-'} ${p.date ?? '-'}`);
    if (n(p.hs) == null || !fresh(ms)) continue;
    stations.push({ name: p.sensor, code: `cco-${p.id}`, kind: 'buoy', lat: +(+lat).toFixed(3), lon: +(+lon).toFixed(3), ms,
      h: n(p.hs), p: n(p.tp), d: n(p.pdir), hmax: n(p.hmax), tz: n(p.tz), spread: n(p.spread), sst: n(p.sst) });
  }
  console.log(`CCO: ${stations.length} with a recent wave height`);
} catch (e) { console.log('CCO failed:', e.message); }

// The last 24 hours from the same buoys, for a trend line: every reading
// (usually half-hourly) as [time, height, period, direction].
if (CCO_KEY && stations.length) try {
  const geo = JSON.parse(await get(`https://coastalmonitoring.org/observations/waves/latest?key=${CCO_KEY}&format=json&duration=24`));
  const n = (v) => (v == null || v === '' ? null : +v), byId = {};
  for (const f of geo.features || []) {
    const p = f.properties || {}, m = /^(\d{4})(\d\d)(\d\d)#(\d\d)(\d\d)/.exec(p.date || '');
    if (!m || n(p.hs) == null) continue;
    (byId[`cco-${p.id}`] ||= []).push([Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]), n(p.hs), n(p.tp), n(p.pdir)]);
  }
  for (const s of stations) {
    const h = byId[s.code];
    if (!h) continue;
    const seen = new Set();
    s.hist = h.filter(([t]) => t > Date.now() - 25 * 3600e3 && !seen.has(t) && seen.add(t)).sort((x, y) => x[0] - y[0]);
  }
  console.log(`CCO history: ${(geo.features || []).length} readings; ${stations.filter((s) => s.hist).map((s) => `${s.name} ${s.hist.length}`).join(', ')}`);
} catch (e) { console.log('CCO history failed:', e.message); }

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

for (const line of lines.slice(2)) {
  const f = line.trim().split(/\s+/);
  if (f.length < head.length) continue;
  const num = (n) => (f[col(n)] === 'MM' ? null : +f[col(n)]);
  const lat = num('LAT'), lon = num('LON'), h = num('WVHT');
  if (lat == null || lat < BOX.s || lat > BOX.n || lon < BOX.w || lon > BOX.e || irishSea(lat, lon)) continue;
  const id = f[col('STN')], name = names[id.toUpperCase()] || `Station ${id}`;
  const ms = Date.UTC(+f[col('YYYY')], +f[col('MM')] - 1, +f[col('DD')], +f[col('hh')], +f[col('mm')]);
  const p = num('DPD') ?? num('APD'), d = num('MWD'), ws = num('WSPD'), wd = num('WDIR');
  console.log(`  ${id} ${name} ${lat},${lon} waves=${h ?? '-'} m period=${p ?? '-'} s dir=${d ?? '-'} ${new Date(ms).toISOString()}`);
  if (h == null || !fresh(ms)) continue;
  stations.push({ name: name.replace(/\s+AWS$/, ''), code: id, kind: 'platform', lat, lon, ms, h, p, d, ws, wd });
}
console.log(`${stations.length} stations in all with a wave height in the last ${HOURS} h`);

// Each platform's last 48 hours from NDBC (newest first; same columns as
// latest_obs.txt, with the year as YY).
await Promise.all(stations.filter((s) => s.kind === 'platform').map(async (s) => {
  try {
    const t = (await get(`https://www.ndbc.noaa.gov/data/realtime2/${s.code}.txt`)).split('\n');
    const hd = t[0].replace(/^#/, '').trim().split(/\s+/), c = (n) => hd.indexOf(n), rows = [];
    for (const line of t.slice(2)) {
      const f = line.trim().split(/\s+/);
      if (f.length < hd.length) continue;
      const v = (n) => (c(n) < 0 || f[c(n)] === 'MM' ? null : +f[c(n)]);
      const ms = Date.UTC(+f[c('YY')], +f[c('MM')] - 1, +f[c('DD')], +f[c('hh')], +f[c('mm')]);
      if (Date.now() - ms > KEEP) break;
      if (v('WVHT') != null) rows.push([ms, v('WVHT'), v('DPD') ?? v('APD'), v('MWD')]);
    }
    if (rows.length) s.hist = rows.reverse();
    console.log(`  ${s.code} ${s.name}: ${rows.length} readings in the last 48 h`);
  } catch (e) { console.log(`  ${s.code} ${s.name}: no history (${e.message})`); }
}));

// Extend every station's history with what we published last time (the
// sources' own history wins where both have a reading), and this reading.
try {
  const prev = JSON.parse(await get(`https://raw.githubusercontent.com/${REPO}/data/waves.json?t=${Date.now()}`));
  const old = Object.fromEntries((prev.stations || []).map((s) => [s.code, s.hist || []]));
  for (const s of stations) {
    const all = new Map();
    for (const r of [...(old[s.code] || []), ...(s.hist || []), [s.ms, s.h, s.p ?? null, s.d ?? null]]) all.set(r[0], r);
    s.hist = [...all.values()].filter((r) => Date.now() - r[0] <= KEEP).sort((a, b) => a[0] - b[0]);
  }
  console.log(`History: ${stations.map((s) => `${s.name} ${s.hist.length}`).join(', ')}`);
} catch (e) { console.log('No earlier waves.json to extend:', e.message); }
writeFileSync(process.argv[2] || 'waves.json', JSON.stringify({ at: Date.now(), source: 'Coastal Monitoring network and NOAA NDBC', hours: HOURS, stations }));
