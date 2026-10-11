// Collects the latest measured waves around the North Sea from EMODnet Physics
// (Europe's near-real-time ocean observations) and writes them as JSON to the
// path given as the first argument. Run every half hour by
// .github/workflows/waves.yml; the app reads the result, which is quicker and
// more reliable than querying EMODnet from a phone.
//
// EMODnet's ERDDAP server describes its own datasets, so instead of
// hard-coding dataset and column names we find them by CF standard name.
// Everything found is logged, so the Actions log shows what was used.
import { writeFileSync } from 'node:fs';

const ERDDAP = 'https://erddap.emodnet-physics.eu/erddap';
const BOX = { s: 53.5, n: 75, w: -12, e: 32 };
const HOURS = 6;    // older readings than this aren't "latest"
const PER_KIND = 8; // datasets to read per measurement, collections first
const KINDS = {
  h: ['sea_surface_wave_significant_height', 'sea_surface_wave_mean_height_of_highest_third'],
  p: ['sea_surface_wave_period_at_variance_spectral_density_maximum', 'sea_surface_wave_mean_period_from_variance_spectral_density_second_frequency_moment',
    'sea_surface_wave_zero_upcrossing_period', 'sea_surface_wave_mean_period'],
  d: ['sea_surface_wave_from_direction', 'sea_surface_wave_from_direction_at_variance_spectral_density_maximum']
};
const enc = encodeURIComponent;

async function erddap(path) {
  const t0 = Date.now();
  const r = await fetch(ERDDAP + path, { signal: AbortSignal.timeout(90e3) });
  const ms = Date.now() - t0;
  if (r.status === 404) { console.log(`  404 (no rows) ${ms} ms  ${path.slice(0, 140)}`); return []; }
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${path.slice(0, 140)}: ${(await r.text()).slice(0, 300)}`);
  const t = (await r.json()).table;
  console.log(`  ${t.rows.length} rows ${ms} ms  ${path.slice(0, 140)}`);
  return t.rows.map((row) => Object.fromEntries(t.columnNames.map((c, i) => [c, row[i]])));
}

async function findDatasets(kind, names) {
  const ids = new Set();
  for (const sn of names) {
    const rows = await erddap(`/search/advanced.json?searchFor=&protocol=tabledap&standard_name=${enc(sn)}` +
      `&minLat=${BOX.s}&maxLat=${BOX.n}&minLon=${BOX.w}&maxLon=${BOX.e}&minTime=now-2days&page=1&itemsPerPage=500`).catch((e) => { console.log('  search failed:', e.message); return []; });
    rows.forEach((r) => ids.add(r['Dataset ID']));
  }
  console.log(`${kind}: ${ids.size} datasets: ${[...ids].slice(0, 40).join(', ')}${ids.size > 40 ? ' …' : ''}`);
  // Multi-station collections first: one query covers many stations.
  const coll = (id) => /^ERD_EP_|_EP_|INSTAC|^TS_/i.test(id);
  const ranked = [...ids].sort((a, b) => coll(b) - coll(a));
  const sets = [];
  for (const id of ranked) {
    if (sets.length >= PER_KIND) break;
    const info = await erddap(`/info/${enc(id)}/index.json`).catch((e) => { console.log('  info failed:', e.message); return []; });
    const vars = {};
    info.forEach((r) => {
      const v = r['Variable Name'];
      vars[v] = vars[v] || {};
      if (r['Row Type'] === 'attribute') vars[v][r['Attribute Name']] = r.Value;
    });
    const pick = (test) => Object.keys(vars).find((v) => v !== 'NC_GLOBAL' && test(v, vars[v]));
    const value = names.map((sn) => pick((v, a) => a.standard_name === sn && !/_QC$|_DM$/i.test(v))).find(Boolean);
    const lat = pick((v, a) => v === 'latitude' || a.standard_name === 'latitude');
    const lon = pick((v, a) => v === 'longitude' || a.standard_name === 'longitude');
    const time = pick((v, a) => v === 'time' || a.standard_name === 'time');
    const station = pick((v, a) => a.cf_role === 'timeseries_id') || pick((v) => /^(platform_?code|platform_?id|station_?id|EP_PLATFORM_ID)$/i.test(v));
    const name = pick((v, a) => v !== station && /platform_?name|station_?name/i.test(v + ' ' + (a.long_name || '')));
    const set = { id, value, lat, lon, time, station, name, title: (vars.NC_GLOBAL || {}).title || id };
    console.log(`  ${id}: ${JSON.stringify({ value, lat, lon, time, station, name })}`);
    if (value && lat && lon && time) sets.push(set);
  }
  return sets;
}

async function latest(set) {
  const cols = [set.station, set.name, set.time, set.lat, set.lon, set.value].filter(Boolean);
  const q = [cols.join(','), `${set.time}>=now-${HOURS}hours`, `${set.lat}>=${BOX.s}`, `${set.lat}<=${BOX.n}`,
    `${set.lon}>=${BOX.w}`, `${set.lon}<=${BOX.e}`, `${set.value}!=NaN`,
    `orderByMax("${set.station ? set.station + ',' : ''}${set.time}")`].map(enc).join('&');
  const rows = await erddap(`/tabledap/${enc(set.id)}.json?${q}`);
  return rows.map((r) => ({
    code: set.station ? String(r[set.station]) : set.id,
    name: String((set.name && r[set.name]) || (set.station ? r[set.station] : set.title)).trim(),
    lat: +r[set.lat], lon: +r[set.lon], ms: Date.parse(r[set.time]), v: +r[set.value]
  })).filter((x) => isFinite(x.lat) && isFinite(x.lon) && isFinite(x.v) && x.ms);
}

const out = process.argv[2] || 'waves.json';
const at = {}; // stations keyed by position, since one buoy can sit in several datasets
const key = (x) => `${x.lat.toFixed(1)},${x.lon.toFixed(1)}`;
const used = {};
for (const [kind, names] of Object.entries(KINDS)) {
  const sets = await findDatasets(kind, names);
  used[kind] = sets.map((s) => s.id);
  for (const set of sets) {
    const rows = await latest(set).catch((e) => { console.log(`  ${set.id} query failed: ${e.message}`); return []; });
    rows.forEach((x) => {
      const s = at[key(x)] = at[key(x)] || { lat: x.lat, lon: x.lon, name: x.name, code: x.code };
      if (!s[kind] || x.ms > s[kind].ms) s[kind] = { v: x.v, ms: x.ms };
      if (kind === 'h' && x.name && x.name !== x.code) s.name = x.name;
    });
  }
}
const stations = Object.values(at).filter((s) => s.h).map((s) => ({
  name: s.name, code: s.code, lat: +s.lat.toFixed(3), lon: +s.lon.toFixed(3), ms: s.h.ms,
  h: +s.h.v.toFixed(2), p: s.p ? +s.p.v.toFixed(1) : null, d: s.d ? Math.round(s.d.v) : null
}));
console.log(`\n${stations.length} stations with a wave height in the last ${HOURS} h:`);
stations.forEach((s) => console.log(`  ${s.name} (${s.code}) ${s.lat},${s.lon}  ${s.h} m  ${s.p ?? '-'} s  ${s.d ?? '-'}°  ${new Date(s.ms).toISOString()}`));
writeFileSync(out, JSON.stringify({ at: Date.now(), source: 'EMODnet Physics', hours: HOURS, datasets: used, stations }));
console.log(`\nWrote ${out}`);
