// Collects the latest measured waves around the North Sea and writes them as
// JSON to the path given as the first argument. Sources: NOAA's NDBC, which
// relays the latest report from buoys and platforms worldwide (including North
// Sea and Norwegian ones on the WMO network) in one text file, and EMODnet
// Physics (Europe's near-real-time ocean observations). Run every half hour by
// .github/workflows/waves.yml; the app reads the result, which is quicker and
// more reliable than querying EMODnet from a phone.
//
// EMODnet's ERDDAP server describes its own datasets, so instead of
// hard-coding dataset and column names we find them by CF standard name.
// Everything found is logged, so the Actions log shows what was used.
import { writeFileSync } from 'node:fs';

// EMODnet runs two ERDDAP servers: erddap.emodnet-physics.eu mostly holds
// gliders, while the near-real-time collections from fixed buoys and platforms
// are on er2webapps. ERDDAP_URL overrides it for testing.
const ERDDAP = process.env.ERDDAP_URL || 'https://er2webapps.emodnet-physics.eu/erddap';
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

// --probe: describe what the server holds instead of collecting, to work out
// dataset and column names when collection finds nothing. Writes no file.
if (process.argv.includes('--probe')) {
  const safe = (p) => erddap(p).catch((e) => { console.log('  failed:', e.message); return []; });
  console.log('Wave-related standard names on the server:');
  const names = (await safe('/categorize/standard_name/index.json')).map((r) => r.Category || Object.values(r)[0]).filter((n) => /wave/i.test(n));
  console.log('  ' + names.join('\n  '));
  for (const n of names.slice(0, 12)) {
    const ds = await safe(`/categorize/standard_name/${enc(n)}/index.json`);
    console.log(`${n}: ${ds.length} datasets: ${ds.slice(0, 25).map((r) => r['Dataset ID']).join(', ')}`);
  }
  for (const base of [ERDDAP, 'https://erddap.emodnet-physics.eu/erddap']) {
    const get = (p) => fetch(base + p, { signal: AbortSignal.timeout(90e3) }).then(async (r) => (r.ok ? (await r.json()).table : { rows: [], columnNames: [], status: r.status })).catch((e) => ({ rows: [], columnNames: [], error: e.message }));
    const idx = await get('/info/index.json?page=1&itemsPerPage=5000');
    const ci = idx.columnNames.indexOf('Dataset ID'), ti = idx.columnNames.indexOf('Title');
    console.log(`\n${base}: ${idx.rows.length} datasets in all ${idx.status || idx.error || ''}`);
    const hits = idx.rows.filter((r) => /wave|VHM0|VGHS|VAVH|VTPK|VMDR|INSTAC|_EP_|TS_/i.test(r[ci] + ' ' + r[ti]));
    hits.slice(0, 80).forEach((r) => console.log(`  ${r[ci]} | ${String(r[ti]).slice(0, 90)}`));
    const sr = await get('/search/index.json?page=1&itemsPerPage=50&searchFor=' + enc('significant wave height'));
    console.log(`  full-text search "significant wave height": ${sr.rows.length} ${sr.status || sr.error || ''}`);
    const si = sr.columnNames.indexOf('Dataset ID');
    sr.rows.slice(0, 30).forEach((r) => console.log(`    ${r[si]}`));
  }
  process.exit(0);
}

// NDBC: latest_obs.txt has one line per station with its newest report.
// Columns: STN LAT LON YYYY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD ...;
// "MM" means missing. Station names come from activestations.xml.
async function ndbc() {
  const get = async (u) => { const r = await fetch(u, { signal: AbortSignal.timeout(60e3) }); if (!r.ok) throw new Error(`HTTP ${r.status} for ${u}`); return r.text(); };
  const [txt, xml] = await Promise.all([get('https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt'), get('https://www.ndbc.noaa.gov/activestations.xml').catch(() => '')]);
  const names = {};
  for (const m of xml.matchAll(/<station\s[^>]*id="([^"]+)"[^>]*name="([^"]*)"/g)) names[m[1].toUpperCase()] = m[2].replace(/&amp;/g, '&');
  const lines = txt.split('\n'), head = lines[0].replace(/^#/, '').trim().split(/\s+/);
  const col = (n) => head.indexOf(n);
  console.log(`NDBC: ${lines.length - 2} stations worldwide; columns ${head.join(' ')}`);
  const out = [];
  for (const line of lines.slice(2)) {
    const f = line.trim().split(/\s+/);
    if (f.length < head.length) continue;
    const num = (n) => (f[col(n)] === 'MM' ? null : +f[col(n)]);
    const lat = num('LAT'), lon = num('LON'), h = num('WVHT');
    if (lat == null || lat < BOX.s || lat > BOX.n || lon < BOX.w || lon > BOX.e) continue;
    const ms = Date.UTC(+f[col('YYYY')], +f[col('MM')] - 1, +f[col('DD')], +f[col('hh')], +f[col('mm')]);
    const id = f[col('STN')];
    console.log(`  NDBC ${id} ${names[id.toUpperCase()] || ''} ${lat},${lon} WVHT=${h ?? 'MM'} DPD=${num('DPD') ?? 'MM'} MWD=${num('MWD') ?? 'MM'} ${new Date(ms).toISOString()}`);
    if (h == null || Date.now() - ms > HOURS * 3600e3) continue;
    out.push({ code: id, name: names[id.toUpperCase()] || `Station ${id}`, lat, lon, ms, h, p: num('DPD') ?? num('APD'), d: num('MWD') });
  }
  console.log(`NDBC: ${out.length} with a wave height in the last ${HOURS} h`);
  return out;
}

const out = process.argv[2] || 'waves.json';
const at = {}; // stations keyed by position, since one buoy can sit in several datasets
const key = (x) => `${x.lat.toFixed(1)},${x.lon.toFixed(1)}`;
const used = {};
for (const x of await ndbc().catch((e) => { console.log('NDBC failed:', e.message); return []; })) {
  const k = key(x);
  at[k] = { lat: x.lat, lon: x.lon, name: x.name, code: x.code, h: { v: x.h, ms: x.ms } };
  if (x.p != null) at[k].p = { v: x.p, ms: x.ms };
  if (x.d != null) at[k].d = { v: x.d, ms: x.ms };
}
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
writeFileSync(out, JSON.stringify({ at: Date.now(), source: 'NOAA NDBC and EMODnet Physics', hours: HOURS, datasets: used, stations }));
console.log(`\nWrote ${out}`);
