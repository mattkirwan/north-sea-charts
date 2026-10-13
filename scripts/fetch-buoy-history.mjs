// Backfills past readings from the Coastal Monitoring network's buoys (CCO API)
// for a range of days, for looking back at a swell from before we kept a
// record: node fetch-buoy-history.mjs FROM TO SENSORS OUT_DIR
// FROM and TO are dates (2026-03-15), SENSORS a comma-separated list of buoy
// names (Whitby,Scarborough). Writes OUT_DIR/<sensor>/<YYYY-MM>.json, merged
// with what's there: {name, rows: [[time, height m, peak period s, peak
// direction from, hmax m, mean period s, spread deg]]}. Run by
// .github/workflows/buoy-history.yml, which keeps them on the history branch.
//
// The API gives observations at a time as /observations/waves/YYYYMMDDHHMMSS
// (its docs), and the latest feed takes duration=hours; we ask a day at a time
// and keep whatever falls in the range.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const [from, to, sensors, out] = process.argv.slice(2);
if (!out) throw new Error('Usage: node fetch-buoy-history.mjs FROM TO SENSORS OUT_DIR');
const KEY = process.env.CCO_API_KEY;
if (!KEY) throw new Error('No CCO_API_KEY');
const t0 = Date.parse(`${from}T00:00:00Z`), t1 = Date.parse(`${to}T23:59:59Z`);
const H = 3600e3;

const get = async (u) => {
  const r = await fetch(u, { headers: { Referer: 'https://mattkirwan.github.io/', Accept: 'application/json, text/plain, */*' }, signal: AbortSignal.timeout(60e3) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.text();
};
const n = (v) => (v == null || v === '' ? null : +v);
const stamp = (ms) => new Date(ms).toISOString().replace(/[-:T]/g, '').slice(0, 14);

const rows = {};
for (const sensor of sensors.split(',')) {
  const got = new Map();
  for (let t = t0; t <= t1; t += 24 * H) {
    // The day from t: try the time-stamped endpoint with a duration either way
    // round (we don't know whether the stamp starts or ends the period).
    for (const [label, ts] of [['start', t], ['end', t + 24 * H]]) {
      const u = `https://coastalmonitoring.org/observations/waves/${stamp(ts)}?key=${KEY}&format=json&sensor=${encodeURIComponent(sensor)}&duration=24`;
      try {
        const geo = JSON.parse(await get(u));
        let kept = 0, first = null, last = null;
        for (const f of geo.features || []) {
          const p = f.properties || {}, m = /^(\d{4})(\d\d)(\d\d)#(\d\d)(\d\d)/.exec(p.date || '');
          if (!m || n(p.hs) == null) continue;
          const ms = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
          first = first == null ? ms : Math.min(first, ms); last = last == null ? ms : Math.max(last, ms);
          if (ms < t0 || ms > t1) continue;
          got.set(ms, [ms, n(p.hs), n(p.tp), n(p.pdir), n(p.hmax), n(p.tz), n(p.spread)]);
          kept++;
        }
        console.log(`${sensor} ${new Date(t).toISOString().slice(0, 10)} (${label}): ${(geo.features || []).length} readings` +
          (first ? ` ${new Date(first).toISOString().slice(0, 16)} to ${new Date(last).toISOString().slice(0, 16)}` : '') + `, ${kept} kept`);
      } catch (e) { console.log(`${sensor} ${new Date(t).toISOString().slice(0, 10)} (${label}): ${e.message}`); }
    }
  }
  rows[sensor] = [...got.values()].sort((a, b) => a[0] - b[0]);
  console.log(`${sensor}: ${rows[sensor].length} readings from ${from} to ${to}`);
}

for (const [sensor, rs] of Object.entries(rows)) {
  const byMonth = {};
  rs.forEach((r) => (byMonth[new Date(r[0]).toISOString().slice(0, 7)] ||= []).push(r));
  for (const [month, add] of Object.entries(byMonth)) {
    const dir = `${out}/${sensor.toLowerCase().replace(/\W+/g, '-')}`, path = `${dir}/${month}.json`;
    let have = { name: sensor, rows: [] };
    try { have = JSON.parse(readFileSync(path, 'utf8')); } catch {}
    const all = new Map(have.rows.map((r) => [r[0], r]));
    add.forEach((r) => all.set(r[0], r));
    mkdirSync(dir, { recursive: true });
    writeFileSync(path, JSON.stringify({ name: sensor, rows: [...all.values()].sort((a, b) => a[0] - b[0]) }));
  }
}
