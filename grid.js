/* North Sea Surf: the grid. Where on the Earth each number sits, for the app.

   scripts/grid.py tells the whole story; in short: a cell is one of NOAA's
   own 0.25° grid points (GFS and GFS-Wave share them), named d4:<row>:<col>
   with row = lat * 4 and col = lon * 4, for keeps (54.75N 1.00W, the wave
   model's cell off Saltburn, is d4:219:-4). The chart's square is only the
   picture the frames are drawn on. Over Saltburn's swell window each run
   also has its beacon points' whole forecasts, in tiles (the manifest's
   cells), which series() fetches as wanted: d4 cells by the coast, and out
   at sea NOAA's whole-degree points, d1:<lat>:<lon>, in tiles of their own. A place people care about is better held as latitude
   and longitude, and resolve()d to a cell when used.

   Everything comes from the manifest, nothing is fixed here, so the frames
   job can change the square or the tiles without a new app. Read by app.js
   (NSSGrid.fromManifest) and by the tests under Node. */
'use strict';

const NSSGrid = (() => {
  const rad = (d) => d * Math.PI / 180, deg = (r) => r * 180 / Math.PI;

  // The square's polar stereographic, from the manifest's PROJ4 string, in km.
  function projection(proj) {
    const p = Object.fromEntries(proj.trim().split(/\s+/).map((t) => t.replace(/^\+/, '').split('=')));
    if (p.proj !== 'stere' || +p.lat_0 !== 90) throw new Error(`not a north polar stereographic: ${proj}`);
    const R = +p.R / (p.units === 'km' ? 1000 : 1), k0 = (1 + Math.sin(rad(+p.lat_ts))) / 2, lon0 = +(p.lon_0 || 0);
    return {
      toKm(lon, lat) {
        const lam = rad(lon - lon0), rho = 2 * R * k0 * Math.tan(Math.PI / 4 - rad(lat) / 2);
        return [rho * Math.sin(lam), -rho * Math.cos(lam)];
      },
      toLonLat(x, y) {
        const c = 2 * Math.atan(Math.hypot(x, y) / (2 * R * k0));
        return [((deg(Math.atan2(x, -y)) + lon0 + 540) % 360) - 180, deg(Math.asin(Math.cos(c)))];
      }
    };
  }

  // ---- Cells (as grid.py: a point on an edge goes north or east) ----
  const wrap = (lon) => ((((lon + 180) % 360) + 360) % 360) - 180;
  function cellId(lat, lon, n) {
    const row = Math.floor(lat * n + 0.5);
    let col = Math.floor(wrap(lon) * n + 0.5);
    if (col === 180 * n) col = -col;
    return `d${n}:${row}:${col}`;
  }
  function parse(id) {
    const m = /^d(\d+):(-?\d+):(-?\d+)$/.exec(String(id));
    if (!m) throw new Error(`not a cell: ${id}`);
    const n = +m[1], row = +m[2], col = +m[3];
    if (n < 1 || Math.abs(row) > 90 * n || col < -180 * n || col >= 180 * n) throw new Error(`not a cell: ${id}`);
    return { n, row, col };
  }
  // Great-circle km and the bearing from a to b.
  function away(lat1, lon1, lat2, lon2) {
    const p1 = rad(lat1), p2 = rad(lat2), dl = rad(lon2 - lon1);
    const a = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    const b = deg(Math.atan2(Math.sin(dl) * Math.cos(p2), Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl)));
    return { km: 2 * 6371.229 * Math.asin(Math.min(1, Math.sqrt(a))), bearing: (b + 360) % 360 };
  }

  // ---- Tiles: cell-series-v1 (grid.py) ----
  // Per variable, cells north to south and west to east, each cell's steps
  // as differences from the step before; pressure low bytes, then high.
  const KINDS = { hs: 'u1', tp: 'u1', tl: 'u1', dl: 'u1', dp: 'u1', u: 'i1', v: 'i1', p: 'u2' };
  function decodeTile(b, vars, cells, steps) {
    const size = cells * steps * vars.reduce((s, k) => s + (KINDS[k] === 'u2' ? 2 : 1), 0);
    if (b.length !== size) throw new Error(`a tile of ${b.length} bytes; ${steps} steps make ${size}`);
    const out = {}, n = cells * steps;
    let o = 0;
    for (const k of vars) {
      const kind = KINDS[k];
      if (!kind) throw new Error(`a tile with ${k} in it`);
      const a = kind === 'u2' ? new Uint16Array(n) : kind === 'i1' ? new Int8Array(n) : new Uint8Array(n);
      for (let c = 0; c < cells; c++) {
        let acc = 0;
        for (let s = 0; s < steps; s++) {
          const m = c * steps + s;
          acc = kind === 'u2' ? (acc + b[o + m] + (b[o + n + m] << 8)) & 65535 : (acc + b[o + m]) & 255;
          a[m] = acc;
        }
      }
      o += kind === 'u2' ? 2 * n : n;
      out[k] = a;
    }
    return out;
  }

  function fromManifest(man, { base = '', get } = {}) {
    const P = projection(man.square.proj), C = man.cells || null, N = C ? C.lattice : 4;
    // Each lattice with tiles: d4, and (since the swell window's cells) the
    // open sea's d1, each with its own tile size, file and tiles.
    const L = {};
    if (C) {
      L[C.lattice] = C;
      if (C.coarse) L[C.coarse.lattice] = C.coarse;
    }
    const tiles = new Map();
    let seaList = null;

    function tileOf(id) {
      const { n, row, col } = parse(id), c = L[n];
      if (!c) return null;
      const lat0 = Math.floor(row / c.tile) * c.tile / n, lon0 = Math.floor(col / c.tile) * c.tile / n;
      const b = C.box, name = `${lat0}_${lon0}`;
      return lat0 >= b.s && lat0 < b.n && lon0 >= b.w && lon0 < b.e && c.tiles.includes(name) ? name : null;
    }
    // A run's tile of lattice n, fetched once (the last few kept).
    function tile(n, name) {
      const key = `${n}/${name}`, c = L[n];
      if (!tiles.has(key)) {
        const url = `${base}${c.file.replace('{dir}', C.dir).replace('{tile}', name)}?run=${man.run}`;
        tiles.set(key, get(url).then((b) => decodeTile(b, C.vars, c.tile * c.tile, man.steps.length)));
        tiles.get(key).catch(() => tiles.delete(key));
        if (tiles.size > 8) tiles.delete(tiles.keys().next().value);
      }
      return tiles.get(key);
    }
    function where(name, id) {
      const { n, row, col } = parse(id), [lat0, lon0] = name.split('_').map(Number);
      const side = L[n].tile;
      return (lat0 * n + side - 1 - row) * side + (col - lon0 * n);
    }
    const isSea = (t, k) => { for (let s = 0; s < man.steps.length; s++) if (t.hs[k * man.steps.length + s] !== 255) return true; return false; };

    const g = {
      lattice: N,
      lonLatToKm: (lon, lat) => P.toKm(lon, lat),
      kmToLonLat: (x, y) => P.toLonLat(x, y),
      cellAt: (lon, lat) => cellId(lat, lon, N),
      cellOf(id) { const { n, row, col } = parse(id); return { lat: row / n, lon: col / n }; },
      // The cell's outline in the square's km, corners and edge midpoints,
      // clockwise from the north-west: lines of latitude curve on the square.
      cellBoundsKm(id) {
        const { n, row, col } = parse(id), h = 0.5 / n, la = row / n, lo = col / n;
        const pts = [[la + h, lo - h], [la + h, lo], [la + h, lo + h], [la, lo + h], [la - h, lo + h], [la - h, lo], [la - h, lo - h], [la, lo - h]];
        return pts.flatMap(([lat, lon]) => P.toKm(lon, lat));
      },
      tileOf,
      // The beacon points, where each is on the Earth and on the square: the
      // manifest's (grid.py's beacon_points(), d4 by the coast and d1 out at
      // sea), or every sea cell from a manifest of before (its sea mask);
      // without a tile. Null for a manifest with neither.
      seaPoints() {
        if (!C || !(C.points || C.sea)) return null;
        if (!seaList) {
          seaList = [];
          const add = (b64, n) => {
            const b = C.box, cols = (b.e - b.w) * n, rows = (b.n - b.s) * n, bits = atob(b64);
            for (let r = 0; r < rows; r++) {
              for (let c = 0; c < cols; c++) {
                const k = r * cols + c;
                if (!((bits.charCodeAt(k >> 3) >> (7 - (k & 7))) & 1)) continue;
                const row = b.n * n - 1 - r, col = b.w * n + c, lat = row / n, lon = col / n, [x, y] = P.toKm(lon, lat);
                seaList.push({ id: `d${n}:${row}:${col}`, n, row, col, lat, lon, x, y });
              }
            }
          };
          add(C.points || C.sea, N);
          if (C.coarse && C.coarse.points) add(C.coarse.points, C.coarse.lattice);
        }
        return seaList;
      },
      // The run's tiles over a box of latitude and longitude (degrees).
      tilesIn(s, n, w, e) {
        if (!C) return [];
        const step = C.tile / C.lattice, out = [];
        for (let la = Math.floor(s / step) * step; la <= n; la += step) {
          for (let lo = Math.floor(w / step) * step; lo <= e; lo += step) {
            const name = `${la}_${lo}`;
            if (C.tiles.includes(name)) out.push(name);
          }
        }
        return out;
      },
      // A tile's cells with sea in them over the run (the grid points a
      // beacon can go on), each with its name and where it is.
      async seaCells(name) {
        const t = await tile(N, name), [lat0, lon0] = name.split('_').map(Number), n = N, out = [];
        for (let row = lat0 * n; row < lat0 * n + C.tile; row++) {
          for (let col = lon0 * n; col < lon0 * n + C.tile; col++) {
            const id = `d${n}:${row}:${col}`;
            if (isSea(t, where(name, id))) out.push({ id, lat: row / n, lon: col / n });
          }
        }
        return out;
      },
      // A cell's forecast over the run, or null outside the tiles: wave
      // height and periods (m, s), the directions the longest swell and the
      // peak waves come from (degrees), the wind towards east and north
      // (m/s) and pressure (hPa), NaN where there are none (land has no sea).
      async series(id) {
        const name = tileOf(id);
        if (!name) return null;
        const t = await tile(parse(id).n, name), k = where(name, id), S = man.steps.length, sc = C.scale;
        const pick = (a, f) => Float32Array.from({ length: S }, (_, s) => f(a[k * S + s]));
        const sea = (q, d) => (q === 255 ? NaN : q / d);
        return {
          id, ...g.cellOf(id), sea: isSea(t, k), run: man.run, steps: man.steps,
          hs: pick(t.hs, (q) => sea(q, sc.hs)), tp: pick(t.tp, (q) => sea(q, sc.tp)), tl: pick(t.tl, (q) => sea(q, sc.tl)),
          dl: pick(t.dl, (q) => (q === 255 ? NaN : q * sc.dir)), dp: pick(t.dp, (q) => (q === 255 ? NaN : q * sc.dir)),
          u: pick(t.u, (q) => (q === -128 ? NaN : q / sc.wind)), v: pick(t.v, (q) => (q === -128 ? NaN : q / sc.wind)),
          p: pick(t.p, (q) => (q === 65535 ? NaN : q / sc.p[0] + sc.p[1]))
        };
      },
      // The cell for a place: its own for the wind ('wind'), the nearest
      // with sea within `within` km for the waves ('waves'), with how far and
      // which way it is from the place; null if there's none.
      async resolve(lat, lon, need = 'waves', within = 60) {
        const own = cellId(lat, lon, N);
        if (need !== 'waves') return { id: own, km: 0, bearing: 0 };
        const { row, col } = parse(own), r = Math.ceil(within / (111 / N * Math.cos(rad(Math.min(80, Math.abs(lat)))))) + 1;
        let best = null;
        for (let dr = -r; dr <= r; dr++) for (let dc = -r; dc <= r; dc++) {
          const id = `d${N}:${row + dr}:${col + dc}`, name = tileOf(id);
          if (!name) continue;
          const c = g.cellOf(id), d = away(lat, lon, c.lat, c.lon);
          if (d.km > within || (best && d.km >= best.km)) continue;
          if (isSea(await tile(N, name), where(name, id))) best = { id, ...d };
        }
        return best;
      }
    };
    return g;
  }

  return { fromManifest, cellId, parse, decodeTile, projection };
})();

if (typeof module !== 'undefined') module.exports = NSSGrid;
