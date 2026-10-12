// Collects the latest measured waves around the North Sea and writes them as
// JSON to the path given as the first argument. Run every half hour by
// .github/workflows/waves.yml; the app reads the result.
//
// Sources:
// - The National Network of Regional Coastal Monitoring Programmes (CCO API):
//   wave buoys round the English coast, including Whitby, with height, peak
//   period and direction. Our key was issued for mattkirwan.github.io; the
//   site is public, so the key is too.
// - NOAA's National Data Buoy Center, which relays the newest report from
//   buoys and platforms worldwide, including North Sea oil and gas platforms
//   (height only) on the WMO network, in one text file (latest_obs.txt).
// EMODnet Physics was tried first, but its ERDDAP servers hold no
// near-real-time wave collections.
import { writeFileSync } from 'node:fs';

const BOX = { s: 53.5, n: 75, w: -12, e: 32 };
const HOURS = 6; // older readings than this aren't "latest"
const CCO_KEY = 'd36f6f6fcf2468bec6d79fe781ee6a03';

const get = async (u) => {
  // The CCO API picks its format from Accept (it sends XML otherwise).
  const r = await fetch(u, { headers: { Referer: 'https://mattkirwan.github.io/', Accept: 'application/json, text/plain, */*' }, signal: AbortSignal.timeout(60e3) });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${u}`);
  return r.text();
};
const unescape = (s) => s.replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

const stations = [];
const fresh = (ms) => ms && Date.now() - ms <= HOURS * 3600e3;

// CCO: GeoJSON of every buoy's latest reading. Dates are "YYYYMMDD#HHMMSS" UTC;
// hs is significant height (m), tp peak period (s), pdir peak direction (deg from).
try {
  const geo = JSON.parse(await get(`https://coastalmonitoring.org/observations/waves/latest?key=${CCO_KEY}&format=json`));
  const n = (v) => (v == null || v === '' ? null : +v);
  for (const f of geo.features || []) {
    const p = f.properties || {}, [lon, lat] = (f.geometry && f.geometry.coordinates) || [];
    const m = /^(\d{4})(\d\d)(\d\d)#(\d\d)(\d\d)/.exec(p.date || '');
    const ms = m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : 0;
    if (lat == null || lat < BOX.s || lat > BOX.n || lon < BOX.w || lon > BOX.e) continue;
    console.log(`  CCO ${p.sensor} ${lat},${lon} waves=${p.hs ?? '-'} m period=${p.tp ?? '-'} s dir=${p.pdir ?? '-'} ${p.date ?? '-'}`);
    if (n(p.hs) == null || !fresh(ms)) continue;
    stations.push({ name: p.sensor, code: `cco-${p.id}`, lat: +(+lat).toFixed(3), lon: +(+lon).toFixed(3), ms, h: n(p.hs), p: n(p.tp), d: n(p.pdir) });
  }
  console.log(`CCO: ${stations.length} with a recent wave height`);
} catch (e) { console.log('CCO failed:', e.message); }

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
  if (lat == null || lat < BOX.s || lat > BOX.n || lon < BOX.w || lon > BOX.e) continue;
  const id = f[col('STN')], name = names[id.toUpperCase()] || `Station ${id}`;
  const ms = Date.UTC(+f[col('YYYY')], +f[col('MM')] - 1, +f[col('DD')], +f[col('hh')], +f[col('mm')]);
  const p = num('DPD') ?? num('APD'), d = num('MWD');
  console.log(`  ${id} ${name} ${lat},${lon} waves=${h ?? '-'} m period=${p ?? '-'} s dir=${d ?? '-'} ${new Date(ms).toISOString()}`);
  if (h == null || !fresh(ms)) continue;
  stations.push({ name: name.replace(/\s+AWS$/, ''), code: id, lat, lon, ms, h, p, d });
}
console.log(`${stations.length} stations in all with a wave height in the last ${HOURS} h`);
writeFileSync(process.argv[2] || 'waves.json', JSON.stringify({ at: Date.now(), source: 'Coastal Monitoring network and NOAA NDBC', hours: HOURS, stations }));
