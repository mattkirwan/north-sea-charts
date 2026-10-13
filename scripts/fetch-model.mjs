// Collects NOAA's wave model forecast (GFS-Wave, WAVEWATCH III) at points
// along the way swell comes to Saltburn and writes it as JSON to the path
// given as the first argument. Run with the wave collector every half hour by
// .github/workflows/waves.yml; the app's long-period watch reads the result.
//
// NOAA runs the model four times a day and publishes, for a few hundred
// buoys and platforms, every swell it sees there, hour by hour for the next
// 7.5 days: height, peak period and direction of each. Ours (WMO numbers):
// the Norwegian Sea at Jan Mayen, the Atlantic west of the Hebrides (K5) and
// west of Shetland (K7), the North Sea platforms from Magnus down, and a point
// 150 km north-east of Saltburn. Long-period swell shows up first in the
// north and then point by point down the North Sea.
//
// The bulletins (gfswave.<id>.bull on NOAA's open data bucket) are kept for
// every run since March 2021, so anything here can be looked up again later.
// Their directions are where the swell is heading; we store where it comes
// from, like the buoys.
import { writeFileSync } from 'node:fs';

const BUCKET = 'https://noaa-gfs-bdp-pds.s3.amazonaws.com';
const REPO = process.env.GITHUB_REPOSITORY || 'mattkirwan/north-sea-charts';
const PUBLISHED = `https://raw.githubusercontent.com/${REPO}/data/model.json`;
const POINTS = [
  { id: '64071', name: 'Jan Mayen' },
  { id: '64045', name: 'West of the Hebrides' },
  { id: '64046', name: 'West of Shetland' },
  { id: '63115', name: 'Magnus' },
  { id: '63110', name: 'Beryl' },
  { id: '62146', name: 'Lomond' },
  { id: '62026', name: 'Off Saltburn', near: true }, // 55.3N 1.1E, 150 km NE
];
const MIN_HS = 0.05; // smaller swells than this (m) aren't kept
const DAYS = 8; // the bulletins go out 16 days; the rest is too far off to use

const H = 3600e3;
const url = (cycle, id) => {
  const d = new Date(cycle), ymd = d.toISOString().slice(0, 10).replace(/-/g, ''), hh = String(d.getUTCHours()).padStart(2, '0');
  return `${BUCKET}/gfs.${ymd}/${hh}/wave/station/bulls.t${hh}z/gfswave.${id}.bull`;
};
const get = async (u, opts = {}) => {
  const r = await fetch(u, { ...opts, signal: AbortSignal.timeout(60e3) });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${u}`);
  return r;
};

// The newest run with bulletins out (they come about 5½ hours after the run).
async function latestCycle() {
  const now = Math.floor(Date.now() / (6 * H)) * 6 * H;
  for (let k = 0; k < 6; k++) {
    const c = now - k * 6 * H;
    try { await get(url(c, POINTS.at(-1).id), { method: 'HEAD' }); return c; } catch {}
  }
  throw new Error('No wave model run found in the last day and a half');
}

// A bulletin's table: "| dd hh | Hst n x | Hs Tp dir | Hs Tp dir | ..." with
// "*" before a swell the local wind is probably making.
function parse(text, cycle) {
  const loc = /Location : \S+\s+\(\s*([\d.]+)([NS])\s+([\d.]+)([EW])\)/.exec(text);
  if (!loc) throw new Error('Not a wave model bulletin');
  const lat = +loc[1] * (loc[2] === 'S' ? -1 : 1), lon = +loc[3] * (loc[4] === 'W' ? -1 : 1);
  const c = new Date(cycle), rows = [];
  let month = c.getUTCMonth(), year = c.getUTCFullYear(), lastDay = c.getUTCDate();
  for (const line of text.split('\n')) {
    const cells = line.split('|');
    const dh = cells[1] && /^\s*(\d+)\s+(\d+)\s*$/.exec(cells[1]);
    if (!dh || cells.length < 5) continue;
    const day = +dh[1];
    if (day < lastDay) { month += 1; if (month > 11) { month = 0; year += 1; } } // into the next month
    lastDay = day;
    const t = Date.UTC(year, month, day, +dh[2]);
    if (t > cycle + DAYS * 24 * H) break;
    const hst = parseFloat(cells[2]);
    const swells = [];
    for (const cell of cells.slice(3)) {
      const a = cell.replace('*', '').trim().split(/\s+/).map(Number);
      if (a.length !== 3 || a.some(Number.isNaN) || a[0] < MIN_HS) continue;
      swells.push([a[0], a[1], (a[2] + 180) % 360, cell.includes('*') ? 1 : 0]);
    }
    rows.push([t, Number.isNaN(hst) ? null : hst, swells]);
  }
  if (!rows.length) throw new Error('Empty bulletin');
  return { lat, lon, rows };
}

const out = process.argv[2];
if (!out) throw new Error('Usage: node fetch-model.mjs OUT.json');
let prev = null;
try { prev = await (await get(`${PUBLISHED}?t=${Date.now()}`)).json(); } catch {}
let model;
try {
  const cycle = await latestCycle();
  if (prev && prev.cycle === cycle && prev.points && prev.points.length === POINTS.length) {
    console.log(`Wave model ${new Date(cycle).toISOString()} already published`);
    model = prev;
  } else {
    const points = await Promise.all(POINTS.map(async (p) => ({ ...p, ...parse(await (await get(url(cycle, p.id))).text(), cycle) })));
    model = { cycle, fetched: Date.now(), source: 'NOAA GFS-Wave (WAVEWATCH III)', points };
    console.log(`Wave model ${new Date(cycle).toISOString()}: ${points.map((p) => `${p.name} ${p.rows.length} h`).join(', ')}`);
  }
} catch (e) {
  if (!prev) throw e;
  console.log(`Keeping the published wave model (${e.message})`);
  model = prev;
}
writeFileSync(out, JSON.stringify(model));
