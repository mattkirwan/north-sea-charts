// The app's grid.js under Node, for test_grid.py: node tests/grid_parity.cjs ASK.json
// ASK has the manifest, the folder standing in for where the tiles are
// published (base), and what to work out: points to project and to name the
// cells of, km to unproject, cells to outline and to read the forecasts of,
// and places to resolve; and every cell the sea mask has sea in. Prints the answers as JSON (NaN as null).
const fs = require('fs'), path = require('path'), zlib = require('zlib');
const NSSGrid = require(path.join(__dirname, '..', 'grid.js'));

(async () => {
  const ask = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const asked = [];
  const g = NSSGrid.fromManifest(ask.manifest, {
    base: ask.base,
    get: async (url) => { asked.push(url); return new Uint8Array(zlib.gunzipSync(fs.readFileSync(url.split('?')[0]))); }
  });
  const arr = (a) => Array.from(a, (x) => (Number.isNaN(x) ? null : x));
  const series = [];
  for (const id of ask.series || []) {
    const s = await g.series(id);
    series.push(s && Object.fromEntries(Object.entries(s).map(([k, v]) => [k, v instanceof Float32Array ? arr(v) : v])));
  }
  const resolved = [];
  for (const [lat, lon, need] of ask.resolve || []) resolved.push(await g.resolve(lat, lon, need));
  process.stdout.write(JSON.stringify({
    km: (ask.points || []).map(([lat, lon]) => g.lonLatToKm(lon, lat)),
    lonlat: (ask.km || []).map(([x, y]) => g.kmToLonLat(x, y)),
    cells: (ask.points || []).map(([lat, lon]) => g.cellAt(lon, lat)),
    tiles: (ask.ids || []).map((id) => g.tileOf(id)),
    bounds: (ask.ids || []).map((id) => g.cellBoundsKm(id)),
    bad: (ask.bad || []).map((id) => { try { g.cellOf(id); return false; } catch { return true; } }),
    sea: (g.seaPoints() || []).map((c) => c.id),
    series, resolved, asked
  }));
})().catch((e) => { console.error(e); process.exit(1); });
