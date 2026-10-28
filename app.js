/* North Sea Surf: the chart screen.

   One full-screen chart of NOAA's GFS and GFS-Wave runs, drawn here from the
   model's fields (scripts/chart_frames.py: one small gzipped grid per frame,
   on the frames branch), and one panel: the key, the band buttons, the time
   readout and the timeline. The panel is either open along the bottom or
   docked to a narrow column on the right; both are in the page, one shown.
   Time moves only on the timeline; the chart pans and zooms like a map. The
   design system's tokens, panel components and icons (ds/) style
   everything; the canvas reads the same tokens. */
'use strict';

const Q = new URLSearchParams(location.search);
const FR = Q.get('frames') || 'https://raw.githubusercontent.com/mattkirwan/north-sea-charts/frames/';
const H = 3600e3, MPH = 2.236936, TICK = 8, MAX_KM_ACROSS = 36;
const $ = (s) => document.querySelector(s);
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
};
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
// Usage stats (Umami, loaded by index.html): the first thing someone does
// beyond looking, once a visit: pan, zoom, rail (the timeline) or band.
let interacted = false;
try { interacted = !!sessionStorage.getItem('nss_fi'); } catch {}
function firstInteraction(type) {
  if (interacted) return;
  interacted = true;
  try { sessionStorage.setItem('nss_fi', '1'); } catch {}
  if (window.umami) umami.track('first_interaction', { type });
}

// ---- Tokens ---------------------------------------------------------------
let C = {};
function readTokens() {
  const cs = getComputedStyle(document.documentElement), v = (n) => cs.getPropertyValue(n).trim();
  C = {
    sea: v('--chart-sea'), land: v('--chart-land'), coast: v('--chart-coast'), grid: v('--chart-grid'),
    iso: v('--chart-isobar'), high: v('--chart-high'), arrow: v('--chart-arrow'),
    height: [1, 2, 3, 4, 5, 6, 7].map((i) => v(`--height-${i}`)),
    period: [1, 2, 3, 4, 5].map((i) => v(`--period-${i}`)),
    wind: [1, 2, 3, 4, 5, 6].map((i) => v(`--wind-${i}`))
  };
}
const FONT = '"Geist Mono", ui-monospace, monospace';
// The design system's icon set (24 px grid, 1.5 px line, square ends).
const ICONS = {
  pressure: '<path d="M3.5 11.5 C3 6 9 3.5 13.5 4.2 C18.5 5 21.5 8.5 20.8 13 C20.2 17.5 15.5 20.5 11 19.8 C6 19 4 16 3.5 11.5 Z"></path><path d="M6.5 11.8 C6.3 8.3 10 6.6 13.2 7.2 C16.6 7.8 18.2 10.2 17.8 13 C17.4 15.8 14.6 17.4 11.6 17 C8.5 16.6 6.7 14.7 6.5 11.8 Z"></path><path d="M9.4 12 C9.3 10.2 11 9.3 12.8 9.6 C14.6 9.9 15.3 11.2 15 12.6 C14.7 14 13.2 14.8 11.7 14.5 C10.2 14.2 9.5 13.3 9.4 12 Z"></path><circle cx="12.3" cy="12.1" r="0.9" fill="currentColor" stroke="none"></circle>',
  wind: '<path d="M3 8 H14 C16.5 8 17.5 5.5 16 4.5 C14.8 3.7 13.2 4.6 13.5 6"></path><path d="M3 12 H18.5 C21 12 22 14.5 20.5 15.8 C19.3 16.8 17.6 16 17.8 14.5"></path><path d="M3 16 H10 C12.3 16 13 18.4 11.6 19.4 C10.5 20.2 9 19.4 9.3 18.1"></path>',
  swell: '<path d="M3 6.5 Q6 3 9 6.5 T15 6.5 T21 6.5"></path><path d="M3 12 Q6 8.5 9 12 T15 12 T21 12"></path><path d="M3 17.5 Q6 14 9 17.5 T15 17.5 T21 17.5"></path>',
  height: '<path d="M3 12 Q5.5 8.5 8 12 T13 12 T17 11"></path><path d="M20.5 7.5 V16.5"></path><path d="M19 7.5 H22"></path><path d="M19 16.5 H22"></path>',
  period: '<path d="M3 13 Q6 9.5 9 13 T15 13 T21 13"></path><path d="M3 6.5 H21"></path><path d="M3 5 V8"></path><path d="M21 5 V8"></path>',
  slide: '<path d="M3 10 H21"></path><path d="M6 7 L3 10 L6 13"></path><path d="M18 7 L21 10 L18 13"></path><path d="M8 15 V19 M12 14 V19 M16 15 V19"></path>',
  reset: '<path d="M17.5 8.5 A7 7 0 1 1 12 5"></path><path d="M12 2.5 L14.5 5 L12 7.5"></path><path d="M12 9 V15"></path>',
  loading: '<circle cx="12" cy="12" r="8" stroke-dasharray="2.4 3"></circle>',
  updated: '<path d="M19 11 A7 7 0 0 0 6.2 8"></path><path d="M5 5 V8.5 H8.5"></path><path d="M5 13 A7 7 0 0 0 17.8 16"></path><path d="M19 19 V15.5 H15.5"></path>',
  offline: '<path d="M12 20 V12"></path><path d="M8.8 9.2 A4.5 4.5 0 0 1 15.2 9.2"></path><path d="M6.2 6.6 A8.2 8.2 0 0 1 17.8 6.6"></path><path d="M4 4 L20 20"></path>',
  old: '<circle cx="12" cy="12" r="8.5"></circle><path d="M12 7 V12 L15.5 14"></path>',
  dock: '<rect x="3" y="4.5" width="18" height="15"></rect><path d="M15.5 4.5 V19.5"></path><path d="M6.5 12 H12.5 M10 9.5 L12.5 12 L10 14.5"></path>',
  open: '<rect x="3" y="4.5" width="18" height="15"></rect><path d="M15.5 4.5 V19.5"></path><path d="M12.5 12 H6.5 M9 9.5 L6.5 12 L9 14.5"></path>'
};
const icon = (n, cls = '') => `<svg class="nss-icon${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n]}</svg>`;
document.querySelectorAll('[data-icon]').forEach((el) => { el.innerHTML = icon(el.dataset.icon); });
const KEYS = {
  wind: { unit: 'Wind, mph', steps: ['10', '20', '25', '30', '40', '50+'], tok: 'wind', lev: [10, 20, 25, 30, 40, 50] },
  height: { unit: 'Swell height, m', steps: ['0.5', '1', '1.5', '2', '3', '4', '6+'], tok: 'height', lev: [0.5, 1, 1.5, 2, 3, 4, 6], fig: (l) => `${l} m` },
  period: { unit: 'Swell period, s', steps: ['8', '10', '12', '14', '16+'], tok: 'period', lev: [8, 10, 12, 14, 16], fig: (l) => `${l} s` }
};

// ---- State ----------------------------------------------------------------
let man = null, frames = [], idx = 0, shown = -1;
let band = store.get('nss.band', 'pressure'), swellVar = store.get('nss.swell', 'height');
let docked = store.get('nss.docked', false);
let offline = false, updatedNote = false, failedAt = {};
const loading = new Set();
let inflight = 0;

// ---- Frames -----------------------------------------------------------------
async function gunzip(buf) {
  const s = new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Uint8Array(await new Response(s).arrayBuffer());
}
function decode(b, P, S) {
  let o = 0;
  const pn = P * P, p = new Uint16Array(pn);
  for (let i = 0; i < P; i++) {
    let acc = 0;
    for (let j = 0; j < P; j++) { const n = i * P + j; acc = (acc + b[o + n] + (b[o + pn + n] << 8)) & 65535; p[n] = acc; }
  }
  o += 2 * pn;
  const rows = (n) => {
    const out = new Uint8Array(n * n);
    for (let i = 0; i < n; i++) { let acc = 0; for (let j = 0; j < n; j++) { const m = i * n + j; acc = (acc + b[o + m]) & 255; out[m] = acc; } }
    o += n * n;
    return out;
  };
  const u = new Int8Array(rows(P).buffer), v = new Int8Array(rows(P).buffer), h = rows(S), t = rows(S);
  return { p, u, v, h, t };
}
// Each run's frames sit in a folder named for it (m.dir), so a frame asked for
// by an older manifest is missing once the next run is published, never the
// next run's frame passed off as this one's. (Manifests from before m.dir:
// the frames at the top of the branch.)
const frameUrl = (m, i) => `${FR}${m.dir ? m.dir + '/' : ''}f${String(m.steps[i]).padStart(m.pad || 3, '0')}.bin.gz?run=${m.run}`;
let goneAt = 0;
async function fetchFrame(m, i) {
  const r = await fetch(frameUrl(m, i), { mode: 'cors', credentials: 'omit' });
  if (!r.ok) {
    // Gone: a newer run has replaced this one. Look for it now, not in five minutes.
    if (r.status === 404 && m === man && Date.now() - goneAt > 30e3) { goneAt = Date.now(); refreshManifest(); }
    throw new Error(`HTTP ${r.status}`);
  }
  return decode(await gunzip(await r.arrayBuffer()), m.grids.p, m.grids.s);
}
function nextToLoad() {
  if (!man) return -1;
  const n = man.steps.length, now = Date.now();
  for (let d = 0; d < n; d++) {
    for (const i of d ? [idx + d, idx - d] : [idx]) {
      if (i < 0 || i >= n || frames[i] || loading.has(i)) continue;
      if (failedAt[i] && now - failedAt[i] < 30e3) continue;
      return i;
    }
  }
  return -1;
}
function pump() {
  while (inflight < 4) {
    const i = nextToLoad();
    if (i < 0) return;
    const m = man;
    loading.add(i); inflight++;
    fetchFrame(m, i).then((d) => {
      if (m !== man) return;
      frames[i] = d; delete failedAt[i]; offline = navigator.onLine === false;
      markTick(i);
      if (i === idx) requestDraw();
      if (Math.abs(i - idx) <= 8) warm();
    }).catch(() => { failedAt[i] = Date.now(); if (!navigator.onLine) offline = true; })
      .finally(() => { loading.delete(i); inflight--; renderStatus(); if (m === man) pump(); });
  }
}
setInterval(pump, 15e3);

// ---- Manifest and new runs ----------------------------------------------------
async function getManifest() {
  const r = await fetch(`${FR}manifest.json?t=${Math.floor(Date.now() / 60e3)}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
const validAt = (m, i) => m.run + m.steps[i] * H;
function nearestIndex(m, t) {
  let best = 0;
  for (let i = 1; i < m.steps.length; i++) if (Math.abs(validAt(m, i) - t) < Math.abs(validAt(m, best) - t)) best = i;
  return best;
}
async function refreshManifest() {
  let m;
  // A manifest from the phone's own copy still counts as offline.
  try { m = await getManifest(); offline = navigator.onLine === false; } catch { offline = true; renderStatus(); return; }
  if (!man) {
    man = m; frames = [];
    idx = nearestIndex(m, Date.now());
    tl.raw = tl.target = idx;
    buildTicks(); setFrame(idx, true); pump(); showTip();
  } else if (m.run > man.run) {
    // Keep the needle on the same valid time: load that frame of the new run first, then swap.
    const t = validAt(man, idx), j = nearestIndex(m, t);
    try {
      const d = await fetchFrame(m, j);
      man = m; frames = []; frames[j] = d; failedAt = {}; idx = j; tl.raw = tl.target = j; geomCache.clear();
      buildTicks(); markTick(j); setFrame(j, true);
      updatedNote = true; setTimeout(fadeUpdated, 3000);
      pump();
    } catch {}
  }
  renderStatus();
}
setInterval(refreshManifest, 5 * 60e3);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { refreshManifest(); buildTicks(); } });
addEventListener('online', () => { offline = false; refreshManifest(); pump(); });
addEventListener('offline', () => { offline = true; renderStatus(); });

// ---- Geometry: marching squares ----------------------------------------------
// Lines where field f (n x n, rows north to south) crosses lev, as polylines in
// grid units [x (column), y (row), ...] with a closed flag.
function contour(f, n, lev) {
  const adj = new Map(), pt = new Map();
  const H_ = (i, j) => (i * n + j) * 2, V_ = (i, j) => (i * n + j) * 2 + 1;
  const link = (a, b) => {
    (adj.get(a) || adj.set(a, []).get(a)).push(b);
    (adj.get(b) || adj.set(b, []).get(b)).push(a);
  };
  const ph = (i, j, a, b) => { const k = H_(i, j); if (!pt.has(k)) pt.set(k, [j + (lev - a) / (b - a), i]); return k; };
  const pv = (i, j, a, b) => { const k = V_(i, j); if (!pt.has(k)) pt.set(k, [j, i + (lev - a) / (b - a)]); return k; };
  for (let i = 0; i < n - 1; i++) {
    for (let j = 0; j < n - 1; j++) {
      const a = f[i * n + j], b = f[i * n + j + 1], c = f[(i + 1) * n + j + 1], d = f[(i + 1) * n + j];
      const code = (a >= lev ? 8 : 0) | (b >= lev ? 4 : 0) | (c >= lev ? 2 : 0) | (d >= lev ? 1 : 0);
      if (code === 0 || code === 15) continue;
      const T = () => ph(i, j, a, b), R = () => pv(i, j + 1, b, c), B = () => ph(i + 1, j, d, c), L = () => pv(i, j, a, d);
      switch (code) {
        case 1: case 14: link(L(), B()); break;
        case 2: case 13: link(B(), R()); break;
        case 3: case 12: link(L(), R()); break;
        case 4: case 11: link(T(), R()); break;
        case 6: case 9: link(T(), B()); break;
        case 7: case 8: link(T(), L()); break;
        case 5: if ((a + b + c + d) / 4 >= lev) { link(T(), L()); link(B(), R()); } else { link(T(), R()); link(L(), B()); } break;
        case 10: if ((a + b + c + d) / 4 >= lev) { link(T(), R()); link(L(), B()); } else { link(T(), L()); link(B(), R()); } break;
      }
    }
  }
  const seen = new Set(), lines = [];
  const walk = (start) => {
    const out = [], first = start;
    let prev = -1, cur = start;
    while (true) {
      seen.add(cur);
      const p = pt.get(cur); out.push(p[0], p[1]);
      const nb = adj.get(cur), nx = nb.find((e) => e !== prev && !seen.has(e));
      if (nx === undefined) {
        const closed = nb.length === 2 && nb.includes(first) && cur !== first && out.length > 4;
        if (closed) { const q = pt.get(first); out.push(q[0], q[1]); }
        return { pts: out, closed };
      }
      prev = cur; cur = nx;
    }
  };
  for (const [e, nb] of adj) if (nb.length === 1 && !seen.has(e)) lines.push(walk(e));
  for (const e of adj.keys()) if (!seen.has(e)) lines.push(walk(e));
  return lines;
}
function chaikin(pts, closed, iters) {
  for (let it = 0; it < iters; it++) {
    const n = pts.length / 2;
    if (n < 3) return pts;
    const out = [];
    if (!closed) out.push(pts[0], pts[1]);
    const last = closed ? n - 1 : n - 2;
    for (let k = 0; k <= last; k++) {
      const x0 = pts[2 * k], y0 = pts[2 * k + 1], k1 = (k + 1) % n, x1 = pts[2 * k1], y1 = pts[2 * k1 + 1];
      out.push(0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1, 0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1);
    }
    if (closed) out.push(out[0], out[1]); else out.push(pts[2 * n - 2], pts[2 * n - 1]);
    pts = out;
  }
  return pts;
}
function bilinear(f, n, x, y) {
  const j = Math.max(0, Math.min(n - 1.001, x)), i = Math.max(0, Math.min(n - 1.001, y));
  const j0 = j | 0, i0 = i | 0, fx = j - j0, fy = i - i0;
  const a = f[i0 * n + j0], b = f[i0 * n + j0 + 1], c = f[(i0 + 1) * n + j0], d = f[(i0 + 1) * n + j0 + 1];
  return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy;
}
function boxBlur(f, n, r, passes) {
  let a = Float32Array.from(f), b = new Float32Array(f.length);
  for (let p = 0; p < passes; p++) {
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      let s = 0, c = 0;
      for (let dj = -r; dj <= r; dj++) { const jj = j + dj; if (jj >= 0 && jj < n) { s += a[i * n + jj]; c++; } }
      b[i * n + j] = s / c;
    }
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      let s = 0, c = 0;
      for (let di = -r; di <= r; di++) { const ii = i + di; if (ii >= 0 && ii < n) { s += b[ii * n + j]; c++; } }
      a[i * n + j] = s / c;
    }
  }
  return a;
}

// Grid units to the square's km (x east, y north).
const toWorld = (sq, n, off) => (pts) => {
  const out = new Float64Array(pts.length), sx = (sq.x1 - sq.x0) / (n - 1), sy = (sq.y0 - sq.y1) / (n - 1);
  for (let k = 0; k < pts.length; k += 2) { out[k] = sq.x0 + (pts[k] - off) * sx; out[k + 1] = sq.y0 - (pts[k + 1] - off) * sy; }
  return out;
};
const pathOf = (lines, closed) => {
  const p = new Path2D();
  for (const l of lines) {
    p.moveTo(l[0], l[1]);
    for (let k = 2; k < l.length; k += 2) p.lineTo(l[k], l[k + 1]);
    if (closed) p.closePath();
  }
  return p;
};

// ---- Geometry per frame ---------------------------------------------------------
const geomCache = new Map();
function cached(key, make) {
  if (geomCache.has(key)) { const g = geomCache.get(key); geomCache.delete(key); geomCache.set(key, g); return g; }
  const g = make();
  geomCache.set(key, g);
  if (geomCache.size > 60) geomCache.delete(geomCache.keys().next().value);
  return g;
}
function pressureGeom(i) {
  return cached(`p${man.run}:${i}`, () => {
    const P = man.grids.p, d = frames[i], [scale, base] = man.scale.p, f = new Float32Array(P * P);
    let lo = Infinity, hi = -Infinity;
    for (let k = 0; k < f.length; k++) { f[k] = d.p[k] / scale + base; lo = Math.min(lo, f[k]); hi = Math.max(hi, f[k]); }
    // Where the wind turns cyclonic (round a low) the Laplacian of pressure is
    // positive: solid lines there, dotted round highs.
    const bl = boxBlur(f, P, 2, 3), lap = new Float32Array(P * P);
    for (let a = 1; a < P - 1; a++) for (let b = 1; b < P - 1; b++) {
      const k = a * P + b;
      lap[k] = bl[k - 1] + bl[k + 1] + bl[k - P] + bl[k + P] - 4 * bl[k];
    }
    const w = toWorld(man.square, P, 0), lows = [], highs = [], labelled = [];
    for (let lev = Math.ceil(lo / 4) * 4; lev <= hi; lev += 4) {
      for (const line of contour(f, P, lev)) {
        const s = chaikin(line.pts, line.closed, 2);
        if (lev % 12 === 0) labelled.push({ lev, pts: w(s) });
        let run = [s[0], s[1]], cyc = bilinear(lap, P, s[0], s[1]) > 0;
        for (let k = 2; k < s.length; k += 2) {
          run.push(s[k], s[k + 1]);
          const c = bilinear(lap, P, s[k], s[k + 1]) > 0;
          if (c !== cyc) { (cyc ? lows : highs).push(w(run)); run = [s[k], s[k + 1]]; cyc = c; }
        }
        if (run.length > 2) (cyc ? lows : highs).push(w(run));
      }
    }
    // Centres: the lowest or highest point within ~200 km, standing out from its surroundings.
    const sm = boxBlur(f, P, 1, 1), R = 5, cands = [];
    for (let a = 3; a < P - 3; a++) for (let b = 3; b < P - 3; b++) {
      const v = sm[a * P + b];
      let isMin = true, isMax = true, ring = 0, rn = 0;
      for (let da = -R; da <= R && (isMin || isMax); da++) for (let db = -R; db <= R; db++) {
        const aa = a + da, bb = b + db;
        if ((!da && !db) || aa < 0 || bb < 0 || aa >= P || bb >= P) continue;
        const u = sm[aa * P + bb];
        if (u <= v) isMin = false;
        if (u >= v) isMax = false;
        if (Math.abs(da) === R || Math.abs(db) === R) { ring += u; rn++; }
      }
      if (!rn) continue;
      const depth = Math.abs(ring / rn - v);
      if ((isMin || isMax) && depth >= 1.5) cands.push({ a, b, low: isMin, depth, val: Math.round(f[a * P + b]) });
    }
    cands.sort((x, y) => y.depth - x.depth);
    const centres = [];
    for (const c of cands) if (!centres.some((o) => Math.hypot(o.a - c.a, o.b - c.b) < 9)) centres.push(c);
    const cw = w(centres.flatMap((c) => [c.b, c.a]));
    return {
      lows: pathOf(lows, false), highs: pathOf(highs, false), labelled,
      centres: centres.map((c, k) => ({ x: cw[2 * k], y: cw[2 * k + 1], low: c.low, val: c.val }))
    };
  });
}
// Wind speed (mph) as filled bands, like the swell's: a slate field under the arrows.
function windGeom(i) {
  return cached(`wind${man.run}:${i}`, () => {
    const P = man.grids.p, d = frames[i], ws = man.scale.wind || 2, n = P + 2, f = new Float32Array(n * n).fill(-1e9);
    for (let a = 0; a < P; a++) for (let b = 0; b < P; b++) f[(a + 1) * n + b + 1] = Math.hypot(d.u[a * P + b], d.v[a * P + b]) / ws * MPH;
    const w = toWorld(man.square, P, 1);
    return KEYS.wind.lev.map((lev) => pathOf(contour(f, n, lev).map((l) => w(chaikin(l.pts, true, 1))), true));
  });
}
function swellGeom(i, which) {
  return cached(`${which}${man.run}:${i}`, () => {
    const S = man.grids.s, d = frames[i], src = which === 'height' ? d.h : d.t, sc = man.scale[which === 'height' ? 'h' : 't'];
    const n = S + 2, f = new Float32Array(n * n).fill(-1e9);
    for (let a = 0; a < S; a++) for (let b = 0; b < S; b++) { const q = src[a * S + b]; if (q !== 255) f[(a + 1) * n + b + 1] = q / sc; }
    const w = toWorld(man.square, S, 1), levels = KEYS[which].lev;
    const bands = levels.map((lev) => {
      const rings = contour(f, n, lev).map((l) => w(chaikin(l.pts, true, 1)));
      return { lev, rings, path: pathOf(rings, true) };
    });
    return { bands, raw: f, n };
  });
}

// ---- Base map --------------------------------------------------------------------
let baseMap = null;
fetch('assets/base.json').then((r) => r.json()).then((b) => {
  const dec = (a) => {
    const out = new Float64Array(a.length);
    let x = 0, y = 0;
    for (let k = 0; k < a.length; k += 2) { x += a[k]; y += a[k + 1]; out[k] = x * b.unit; out[k + 1] = y * b.unit; }
    return out;
  };
  const thin = (r, d) => {
    // Every point at least d km from the last one kept: enough when zoomed out.
    const out = [r[0], r[1]];
    for (let k = 2; k < r.length; k += 2) {
      if (Math.hypot(r[k] - out[out.length - 2], r[k + 1] - out[out.length - 1]) >= d) out.push(r[k], r[k + 1]);
    }
    return out.length >= 6 ? out : null;
  };
  const rings = b.land.map(dec);
  baseMap = { land: pathOf(rings, true), coarse: pathOf(rings.map((r) => thin(r, 3)).filter(Boolean), true), grid: pathOf(b.grid.map(dec), false) };
  requestDraw();
}).catch(() => {});

// ---- View: pan and zoom -------------------------------------------------------------
const cv = $('#chart'), ctx = cv.getContext('2d');
let W = 0, Hs = 0, dpr = 1;
const SQ = { x0: -2805, x1: 1795, y0: -650, y1: -5250 }, SIDE = 4600;
const COL_W = 64;
const panelH = () => $('#panel').offsetHeight;
// The part of the screen the chart has to itself: above the open panel, or
// left of the docked column.
const vis = () => (docked ? { w: Math.max(100, W - COL_W), h: Hs } : { w: W, h: Math.max(100, Hs - panelH()) });
// Everything right of x and below y is under the panel.
const panelBox = () => (docked ? { x: W - COL_W, y: $('#column').offsetTop } : { x: 0, y: Hs - panelH() });
const kMin = () => { const v = vis(); return Math.min(v.w, v.h) / SIDE; }, kMax = () => W / MAX_KM_ACROSS;
let view = store.get('nss.view', null);
function fitHome() {
  // Iceland and Svalbard down to the UK.
  const bx0 = -1450, bx1 = 1000, by0 = -760, by1 = -4480, v = vis();
  const k = Math.min(v.w / (bx1 - bx0), v.h / (by0 - by1)) * 0.98;
  view = { x: (bx0 + bx1) / 2 + (W - v.w) / (2 * k), y: (by0 + by1) / 2 - (Hs - v.h) / (2 * k), k };
}
function clampView() {
  const v = vis();
  view.k = Math.max(kMin(), Math.min(kMax(), view.k));
  const k = view.k, halfW = v.w / (2 * k), halfH = v.h / (2 * k), ox = (W - v.w) / (2 * k), oy = (Hs - v.h) / (2 * k);
  let vx = view.x - ox, vy = view.y + oy;   // world point at the middle of the visible chart
  vx = 2 * halfW >= SIDE ? (SQ.x0 + SQ.x1) / 2 : Math.max(SQ.x0 + halfW, Math.min(SQ.x1 - halfW, vx));
  vy = 2 * halfH >= SIDE ? (SQ.y0 + SQ.y1) / 2 : Math.max(SQ.y1 + halfH, Math.min(SQ.y0 - halfH, vy));
  view.x = vx + ox; view.y = vy - oy;
}
// After the panel changes shape, ease the map back inside its limits rather
// than jumping.
let clampAnim = 0;
function easeClamp() {
  cancelAnimationFrame(clampAnim);
  const from = { ...view };
  clampView();
  const to = { ...view };
  if (reduced.matches || (from.x === to.x && from.y === to.y && from.k === to.k)) { requestDraw(); saveView(); return; }
  const start = performance.now();
  const step = (t) => {
    const q = Math.min(1, (t - start) / 240), e = 1 - Math.pow(1 - q, 3);
    view = { x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e, k: from.k * Math.pow(to.k / from.k, e) };
    requestDraw();
    if (q < 1) clampAnim = requestAnimationFrame(step); else saveView();
  };
  clampAnim = requestAnimationFrame(step);
}
let saveT = 0;
function saveView() { clearTimeout(saveT); saveT = setTimeout(() => store.set('nss.view', view), 400); }
function zoomAbout(sx, sy, f) {
  const k0 = view.k, wx = view.x + (sx - W / 2) / k0, wy = view.y - (sy - Hs / 2) / k0;
  const k1 = Math.max(kMin(), Math.min(kMax(), k0 * f));
  view.k = k1; view.x = wx - (sx - W / 2) / k1; view.y = wy + (sy - Hs / 2) / k1;
}
function resize() {
  dpr = Math.min(3, devicePixelRatio || 1);
  W = innerWidth; Hs = innerHeight;
  cv.width = Math.round(W * dpr); cv.height = Math.round(Hs * dpr);
  if (!view) fitHome();
  clampView();
  requestDraw();
}
addEventListener('resize', resize);

const ptrs = new Map();
let gesture = null, lastTap = null, zoomAnim = 0;
cv.addEventListener('pointerdown', (e) => {
  cv.setPointerCapture(e.pointerId);
  ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
  cancelAnimationFrame(zoomAnim);
  gesture = { t: performance.now(), x: e.clientX, y: e.clientY, moved: 0, multi: ptrs.size > 1 };
});
cv.addEventListener('pointermove', (e) => {
  const p = ptrs.get(e.pointerId);
  if (!p) return;
  if (ptrs.size === 1) {
    view.x -= (e.clientX - p.x) / view.k; view.y += (e.clientY - p.y) / view.k;
  } else if (ptrs.size === 2) {
    const [a, b] = [...ptrs.values()], o = a === p ? b : a;
    const d0 = Math.hypot(p.x - o.x, p.y - o.y), d1 = Math.hypot(e.clientX - o.x, e.clientY - o.y);
    const mx0 = (p.x + o.x) / 2, my0 = (p.y + o.y) / 2, mx1 = (e.clientX + o.x) / 2, my1 = (e.clientY + o.y) / 2;
    if (d0 > 0) zoomAbout(mx0, my0, d1 / d0);
    view.x -= (mx1 - mx0) / view.k; view.y += (my1 - my0) / view.k;
  }
  if (gesture) gesture.moved += Math.abs(e.clientX - p.x) + Math.abs(e.clientY - p.y);
  if (ptrs.size === 2) firstInteraction('zoom'); else if (gesture && gesture.moved > 10) firstInteraction('pan');
  p.x = e.clientX; p.y = e.clientY;
  clampView(); requestDraw(); saveView();
});
const endPtr = (e) => {
  ptrs.delete(e.pointerId);
  if (ptrs.size || !gesture) return;
  const now = performance.now(), tap = !gesture.multi && gesture.moved < 10 && now - gesture.t < 300;
  if (tap && lastTap && now - lastTap.t < 320 && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 30) {
    animateZoom(e.clientX, e.clientY, 2); lastTap = null; firstInteraction('zoom');
  } else lastTap = tap ? { t: now, x: e.clientX, y: e.clientY } : null;
  gesture = null;
};
cv.addEventListener('pointerup', endPtr);
cv.addEventListener('pointercancel', endPtr);
cv.addEventListener('wheel', (e) => { e.preventDefault(); firstInteraction('zoom'); zoomAbout(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.002)); clampView(); requestDraw(); saveView(); }, { passive: false });
function animateZoom(sx, sy, f) {
  const start = performance.now(), dur = reduced.matches ? 0 : 260;
  let done = 1;
  const step = (t) => {
    const q = dur ? Math.min(1, (t - start) / dur) : 1, e = 1 - Math.pow(1 - q, 3), target = Math.pow(f, e);
    zoomAbout(sx, sy, target / done); done = target;
    clampView(); requestDraw();
    if (q < 1) zoomAnim = requestAnimationFrame(step); else saveView();
  };
  zoomAnim = requestAnimationFrame(step);
}

// ---- Drawing -----------------------------------------------------------------------
const baseLayer = { canvas: document.createElement('canvas'), key: '' };
let drawQueued = false;
function requestDraw() { if (!drawQueued) { drawQueued = true; requestAnimationFrame(draw); } }
const halo = (text, x, y, fill, haloCol) => {
  ctx.strokeStyle = haloCol; ctx.lineWidth = 3; ctx.lineJoin = 'round'; ctx.strokeText(text, x, y);
  ctx.fillStyle = fill; ctx.fillText(text, x, y);
};
function draw() {
  drawQueued = false;
  if (!W) return;
  const { x, y, k } = view, pb = panelBox();
  const world = () => ctx.setTransform(dpr * k, 0, 0, -dpr * k, dpr * (W / 2 - x * k), dpr * (Hs / 2 + y * k));
  const screen = () => ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const sx = (wx) => W / 2 + (wx - x) * k, sy = (wy) => Hs / 2 - (wy - y) * k;
  screen();
  ctx.fillStyle = C.sea; ctx.fillRect(0, 0, W, Hs);
  const fi = frames[idx] ? idx : shown >= 0 && frames[shown] ? shown : -1;
  if (fi >= 0) shown = fi;
  const swell = band === 'swell' && fi >= 0 ? swellGeom(fi, swellVar) : null;
  if (swell) {
    world();
    const cols = C[KEYS[swellVar].tok];
    swell.bands.forEach((b, i) => { ctx.fillStyle = cols[i]; ctx.fill(b.path, 'evenodd'); });
  }
  if (band === 'wind' && fi >= 0) {
    world();
    windGeom(fi).forEach((p, i) => { ctx.fillStyle = C.wind[i]; ctx.fill(p, 'evenodd'); });
  }
  if (baseMap) {
    // The land, graticule and coast change only when the map moves: kept in
    // their own layer, so moving through time redraws just the weather.
    const key = `${x},${y},${k},${W},${Hs},${dpr}`;
    if (baseLayer.key !== key) {
      const c = baseLayer.canvas, b = c.getContext('2d');
      if (c.width !== cv.width || c.height !== cv.height) { c.width = cv.width; c.height = cv.height; }
      b.setTransform(1, 0, 0, 1, 0, 0); b.clearRect(0, 0, c.width, c.height);
      b.setTransform(dpr * k, 0, 0, -dpr * k, dpr * (W / 2 - x * k), dpr * (Hs / 2 + y * k));
      const land = k < 0.6 ? baseMap.coarse : baseMap.land;
      b.fillStyle = C.land; b.fill(land, 'evenodd');
      b.strokeStyle = C.grid; b.lineWidth = 1 / k; b.stroke(baseMap.grid);
      b.strokeStyle = C.coast; b.lineWidth = 0.8 / k; b.lineJoin = 'round'; b.stroke(land);
      baseLayer.key = key;
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(baseLayer.canvas, 0, 0);
  }
  if (fi < 0) return;
  if (band === 'wind') drawWind(fi, sx, sy, screen);
  // Isobars, centres and their figures on the Pressure band only.
  const g = band === 'pressure' ? pressureGeom(fi) : { centres: [], labelled: [] };
  if (g.lows) {
  world();
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  ctx.strokeStyle = C.iso; ctx.setLineDash([]); ctx.lineWidth = 1.3 / k; ctx.stroke(g.lows);
  ctx.globalAlpha = 0.85; ctx.lineWidth = 1.6 / k; ctx.setLineDash([0.1 / k, 3.5 / k]); ctx.stroke(g.highs);
  ctx.globalAlpha = 1; ctx.setLineDash([]);
  }
  // Figures: centres first, then every third isobar, then swell band edges.
  screen();
  const boxes = [], free = (bx, by, bw, bh) => {
    if (bx < 2 || by < 2 || bx + bw > W - 2 || by + bh > Hs - 2) return false;
    if (bx + bw > pb.x - 4 && by + bh > pb.y - 4) return false;
    if (boxes.some((o) => bx < o[0] + o[2] && o[0] < bx + bw && by < o[1] + o[3] && o[1] < by + bh)) return false;
    boxes.push([bx, by, bw, bh]); return true;
  };
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for (const c of g.centres) {
    const px = sx(c.x), py = sy(c.y), col = c.low ? C.iso : C.high;
    if (!free(px - 16, py - 14, 32, 38)) continue;
    ctx.font = `600 22px ${FONT}`; halo(c.low ? 'L' : 'H', px, py - 2, col, C.sea);
    ctx.font = `400 10px ${FONT}`; halo(String(c.val), px, py + 16, col, C.sea);
  }
  ctx.font = `400 10px ${FONT}`;
  for (const l of g.labelled) placeAlong(l.pts, String(l.lev), 70, 260, sx, sy, free, (t, px, py) => halo(t, px, py, C.iso, C.sea));
  if (swell) {
    const cols = C[KEYS[swellVar].tok];
    swell.bands.forEach((b, i) => {
      const text = KEYS[swellVar].fig(b.lev);
      for (const r of b.rings) placeAlong(r, text, 200, 520, sx, sy, (bx, by, bw, bh) => {
        const wx = x + (bx + bw / 2 - W / 2) / k, wy = y - (by + bh / 2 - Hs / 2) / k;
        return nearSea(swell, wx, wy) && free(bx, by, bw, bh);
      }, (t, px, py) => halo(t, px, py, C.iso, cols[i]));
    });
  }
}
// A swell band's edge along the coast runs under the land: no figures there.
function nearSea(swell, wx, wy) {
  const sq = man.square, n = swell.n, S = n - 2;
  const j = (wx - sq.x0) / (sq.x1 - sq.x0) * (S - 1) + 1, i = (sq.y0 - wy) / (sq.y0 - sq.y1) * (S - 1) + 1;
  for (let a = Math.floor(i) - 1; a <= Math.ceil(i) + 1; a++) for (let b = Math.floor(j) - 1; b <= Math.ceil(j) + 1; b++) {
    if (a < 0 || b < 0 || a >= n || b >= n || swell.raw[a * n + b] < -1e8) return false;
  }
  return true;
}
function placeAlong(pts, text, first, every, sx, sy, free, paint) {
  const tw = ctx.measureText(text).width + 6, th = 12;
  let acc = 0, nextAt = first, px = sx(pts[0]), py = sy(pts[1]);
  for (let k = 2; k < pts.length; k += 2) {
    const qx = sx(pts[k]), qy = sy(pts[k + 1]), seg = Math.hypot(qx - px, qy - py);
    while (acc + seg >= nextAt) {
      const f = (nextAt - acc) / seg, lx = px + (qx - px) * f, ly = py + (qy - py) * f;
      if (free(lx - tw / 2, ly - th / 2, tw, th)) { paint(text, lx, ly); nextAt += every; } else nextAt += 24;
    }
    acc += seg; px = qx; py = qy;
  }
}
function drawWind(fi, sx, sy, screen) {
  const d = frames[fi], P = man.grids.p, sq = man.square, { x, y, k } = view, pb = panelBox();
  const s = 32 / k, x0 = x - W / 2 / k, x1 = x + W / 2 / k, y1 = y + Hs / 2 / k, y0 = y - Hs / 2 / k;
  const path = new Path2D(), ws = man.scale.wind || 2;
  for (let wx = Math.ceil(x0 / s) * s; wx <= x1; wx += s) {
    for (let wy = Math.ceil(y0 / s) * s; wy <= y1; wy += s) {
      if (wx < sq.x0 || wx > sq.x1 || wy > sq.y0 || wy < sq.y1) continue;
      const px = sx(wx), py = sy(wy);
      if (px > pb.x + 10 && py > pb.y + 10) continue;
      const gj = (wx - sq.x0) / (sq.x1 - sq.x0) * (P - 1), gi = (sq.y0 - wy) / (sq.y0 - sq.y1) * (P - 1);
      const u = bilinear(d.u, P, gj, gi) / ws, v = bilinear(d.v, P, gj, gi) / ws, sp = Math.hypot(u, v);
      if (sp < 0.3) continue;
      const dx = u / sp, dy = -v / sp, hx = px + dx * 7, hy = py + dy * 7, p = path;
      p.moveTo(px - dx * 7, py - dy * 7); p.lineTo(hx, hy);
      const a = Math.PI / 6, l = 4.5;
      p.moveTo(hx - l * (dx * Math.cos(a) - dy * Math.sin(a)), hy - l * (dy * Math.cos(a) + dx * Math.sin(a))); p.lineTo(hx, hy);
      p.lineTo(hx - l * (dx * Math.cos(a) + dy * Math.sin(a)), hy - l * (dy * Math.cos(a) - dx * Math.sin(a)));
    }
  }
  screen();
  ctx.lineWidth = 1.6; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.setLineDash([]);
  ctx.strokeStyle = C.arrow; ctx.stroke(path);
}

// ---- Panel: bands, key, swell switch, open or docked ---------------------------------------
const panelEl = $('#panel'), columnEl = $('#column'), flyout = $('#flyout');
function renderPanel() {
  document.querySelectorAll('.nss-band').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.band === band)));
  document.querySelectorAll('[data-swell]').forEach((sw) => {
    sw.hidden = band !== 'swell';
    sw.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.var === swellVar)));
  });
  let unit, html;
  if (band === 'pressure') {
    // The two isobar styles, drawn as the chart draws them.
    const line = (attrs) => `<i class="key-line"><svg aria-hidden="true"><line x1="2" y1="3" x2="92%" y2="3" style="stroke: var(--chart-isobar)" ${attrs}></line></svg></i>`;
    unit = 'Isobars, every 4 hPa';
    html = `<span class="nss-key-unit">${unit}</span><div class="nss-key-steps">` +
      `<span class="nss-key-step">${line('stroke-width="1.3"')}Round lows</span>` +
      `<span class="nss-key-step">${line('stroke-width="1.6" stroke-linecap="round" stroke-dasharray="0.1 3.5" opacity="0.85"')}Round highs</span></div>`;
  } else {
    const K = KEYS[band === 'wind' ? 'wind' : swellVar];
    unit = K.unit;
    html = `<span class="nss-key-unit">${unit}</span><div class="nss-key-steps">` +
      K.steps.map((s, i) => `<span class="nss-key-step"><i style="background: var(--${K.tok}-${i + 1})"></i>${s}</span>`).join('') + '</div>';
  }
  document.querySelectorAll('[data-key]').forEach((k) => { k.setAttribute('aria-label', `${unit} key`); k.innerHTML = html; });
  // Docked, the key floats level with the selected band (and comes in from
  // the column each time it moves).
  const slot = columnEl.querySelector(`.nss-band[data-band="${band}"]`).parentNode;
  if (flyout.parentNode !== slot) slot.appendChild(flyout);
  flyout.hidden = false;
}
document.querySelectorAll('.nss-band').forEach((b) => b.addEventListener('click', () => {
  if (band === b.dataset.band) return;
  band = b.dataset.band; store.set('nss.band', band); firstInteraction('band'); renderPanel(); requestDraw(); warm();
  // The open panel grows or shrinks with the key row: settle the map after.
  if (!docked) setTimeout(easeClamp, reduced.matches ? 0 : 220);
}));
document.querySelectorAll('[data-swell]').forEach((sw) => sw.addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b || b.dataset.var === swellVar) return;
  swellVar = b.dataset.var; store.set('nss.swell', swellVar); renderPanel(); requestDraw(); warm();
}));
function setDocked(d, first) {
  const hadFocus = document.activeElement && document.activeElement.classList.contains('nss-dock-btn');
  docked = d; store.set('nss.docked', d);
  panelEl.toggleAttribute('data-away', d); columnEl.toggleAttribute('data-away', !d);
  panelEl.inert = d; columnEl.inert = !d;
  if (hadFocus) (d ? columnEl : panelEl).querySelector('.nss-dock-btn').focus({ preventScroll: true });
  placeTrack(); renderTips();
  if (!first) easeClamp();
}
document.querySelectorAll('.nss-dock-btn').forEach((b) => b.addEventListener('click', () => setDocked(b.dataset.dock === '1')));

// ---- Time readout and status -------------------------------------------------------------
const fWeek = new Intl.DateTimeFormat('en-GB', { weekday: 'short' });
const fLong = new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
const fHour = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const dayName = (t) => `${fWeek.format(t)} ${new Date(t).getDate()}`;
const setText = (sel, text) => document.querySelectorAll(sel).forEach((el) => { el.textContent = text; });
function renderReadout() {
  if (!man) return;
  const t = validAt(man, idx), label = `Forecast time, ${fLong.format(t)} ${fHour.format(t)}`;
  setText('[data-day]', dayName(t).toUpperCase());
  setText('[data-lead]', `+${man.steps[idx]}H`);
  setText('[data-time]', fHour.format(t));
  $('#readout').setAttribute('aria-label', label);
  $('#colTime').setAttribute('aria-label', label);
}
function runName(m) { const t = m.run; return `run ${fWeek.format(t)} ${String(new Date(t).getUTCHours()).padStart(2, '0')}z`; }
const statusEls = [$('#rStatus'), $('#colStatus')];
function renderStatus() {
  let text = '', kind = '';
  if (!man) [text, kind] = offline ? ['Offline', 'offline'] : ['Loading', 'loading'];
  else if (!frames[idx] && !offline) [text, kind] = ['Loading', 'loading'];
  else if (offline) [text, kind] = [`Offline · ${runName(man)}`, 'offline'];
  else if (Date.now() - man.run > 12 * H) [text, kind] = [`Run ${Math.round((Date.now() - man.run) / H)} h old`, 'old'];
  else if (updatedNote) [text, kind] = [`Updated to ${String(new Date(man.run).getUTCHours()).padStart(2, '0')}z`, 'updated'];
  const [open, col] = statusEls, key = `${kind}|${text}`;
  if (open.dataset.shown === key) return;
  open.dataset.shown = key;
  open.innerHTML = kind ? icon(kind, kind === 'loading' ? ' spin' : '') + `<span>${text}</span>` : '';
  col.innerHTML = kind ? icon(kind, kind === 'loading' ? ' spin' : '') : '';
  col.setAttribute('aria-label', text); col.title = text;
  statusEls.forEach((el) => {
    el.hidden = !kind; delete el.dataset.fading;
    if (kind === 'old') el.dataset.tone = 'warn'; else delete el.dataset.tone;
  });
}
// "Updated to" fades away rather than vanishing.
function fadeUpdated() {
  if (reduced.matches) { updatedNote = false; renderStatus(); return; }
  statusEls.forEach((el) => { el.dataset.fading = ''; });
  setTimeout(() => { updatedNote = false; renderStatus(); }, 400);
}

// ---- Timeline: horizontal in the open panel, vertical in the docked column -------------------
const tl = { raw: 0, target: 0, anim: 0, v: 0 };
const TL = [...document.querySelectorAll('[data-axis]')].map((el) => ({
  el, axis: el.dataset.axis, track: el.querySelector('[data-track]'), tip: el.querySelector('[data-tip]'), ticks: []
}));
function fracIndex(t) {
  const n = man.steps.length;
  if (t <= validAt(man, 0)) return (t - validAt(man, 0)) / H;
  for (let i = 0; i < n - 1; i++) {
    const a = validAt(man, i), b = validAt(man, i + 1);
    if (t < b) return i + (t - a) / (b - a);
  }
  return n - 1 + (t - validAt(man, n - 1)) / (3 * H);
}
function buildTicks() {
  if (!man) return;
  const n = man.steps.length, now = Date.now();
  for (const T of TL) {
    // Later times to the right, or lower down.
    const at = T.axis === 'x' ? 'left' : 'top', label = T.axis === 'x' ? 0 : 3, html = [];
    for (let i = 0; i < n; i++) {
      const t = validAt(man, i), hr = new Date(t).getHours(), three = man.steps[i] > 120 || hr % 3 === 0;
      html.push(`<span class="nss-tick${three ? ' nss-tick--3h' : ''}${t < now ? ' nss-tick--past' : ''}${frames[i] ? '' : ' nss-tick--pending'}" style="${at}:${i * TICK}px"></span>`);
    }
    const first = new Date(validAt(man, 0)); first.setHours(24, 0, 0, 0);
    for (let d = new Date(first); d.getTime() <= validAt(man, n - 1); d.setDate(d.getDate() + 1)) {
      const p = fracIndex(d.getTime()) * TICK, past = d.getTime() < now ? ' nss-day--past' : '';
      const name = T.axis === 'x' ? dayName(d.getTime()) : fWeek.format(d);
      html.push(`<span class="nss-tick nss-tick--day${past ? ' nss-tick--past' : ''}" style="${at}:${p.toFixed(1)}px"></span><span class="nss-day${past}" style="${at}:${(p + label).toFixed(1)}px">${name}</span>`);
    }
    const np = fracIndex(now);
    if (np >= -0.5 && np <= n - 0.5) html.push(`<span class="nss-tick nss-tick--now" style="${at}:${(np * TICK).toFixed(1)}px"></span>`);
    html.push(`<span class="nss-end" style="${at}:${(n - 1) * TICK + 4}px"></span>`);
    T.track.innerHTML = html.join('');
    T.ticks = [...T.track.querySelectorAll('.nss-tick:not(.nss-tick--day):not(.nss-tick--now)')];
    T.el.setAttribute('aria-valuemax', String(n - 1));
  }
  placeTrack();
}
setInterval(buildTicks, 5 * 60e3);
function markTick(i) { for (const T of TL) if (T.ticks[i]) T.ticks[i].classList.remove('nss-tick--pending'); }
const maxPos = () => (man ? man.steps.length - 1 : 0);
function shownPos() {
  // Past either end, the scale stretches a little and springs back.
  const r = tl.raw, m = maxPos(), over = r < 0 ? r : r > m ? r - m : 0;
  return over ? (over < 0 ? 0 : m) + Math.sign(over) * (1 - 1 / (1 + Math.abs(over) * 0.35)) * 4 : r;
}
function placeTrack() {
  const d = (-shownPos() * TICK).toFixed(2);
  for (const T of TL) T.track.style.transform = T.axis === 'x' ? `translateX(${d}px)` : `translateY(${d}px)`;
}
// Build the frames either side of the needle while nothing else is happening,
// so scanning finds them ready.
let warmT = 0;
function warm() {
  clearTimeout(warmT);
  warmT = setTimeout(function next() {
    if (!man) return;
    for (const d of [1, -1, 2, -2, 3, -3, 4, -4, 6, -6, 8, -8]) {
      const i = idx + d;
      if (i < 0 || i >= man.steps.length || !frames[i]) continue;
      const pk = `p${man.run}:${i}`, sk = `${swellVar}${man.run}:${i}`;
      if (!geomCache.has(pk)) { pressureGeom(i); warmT = setTimeout(next, 0); return; }
      if (band === 'swell' && !geomCache.has(sk)) { swellGeom(i, swellVar); warmT = setTimeout(next, 0); return; }
    }
  }, 60);
}
function setFrame(i, force) {
  if (!man) return;
  i = Math.max(0, Math.min(maxPos(), i));
  if (i === idx && !force) return;
  idx = i;
  const t = validAt(man, i);
  for (const T of TL) {
    T.el.setAttribute('aria-valuenow', String(i));
    T.el.setAttribute('aria-valuetext', `${fLong.format(t)}, ${fHour.format(t)}`);
  }
  renderReadout(); renderStatus(); requestDraw(); pump(); warm();
}
function moveTo(raw) {
  tl.raw = raw; placeTrack();
  setFrame(Math.round(Math.max(0, Math.min(maxPos(), raw))));
}
function animateTo(target, dur = 220) {
  cancelAnimationFrame(tl.anim);
  const from = tl.raw, start = performance.now();
  if (reduced.matches) dur = 0;
  const step = (t) => {
    const q = dur ? Math.min(1, (t - start) / dur) : 1, e = 1 - Math.pow(1 - q, 3);
    moveTo(from + (target - from) * e);
    if (q < 1) tl.anim = requestAnimationFrame(step); else scanStopped();
  };
  tl.anim = requestAnimationFrame(step);
}
const settle = () => animateTo(Math.round(Math.max(0, Math.min(maxPos(), tl.raw))));
let drag = null, tlTap = 0;
// How fast the scale was moving as the finger left it, in frames per ms: from
// the last moments of the drag, and none if the finger stopped before lifting.
function releaseSpeed(d, now) {
  const s = d.samples, [t1, r1] = s[s.length - 1], [t0, r0] = s[0];
  if (now - t1 > 120 || t1 - t0 < 8) return 0;
  return (r1 - r0) / (t1 - t0);
}
for (const T of TL) {
  const along = (e) => (T.axis === 'x' ? e.clientX : e.clientY);
  T.el.addEventListener('pointerdown', (e) => {
    if (!man) return;
    T.el.setPointerCapture(e.pointerId);
    cancelAnimationFrame(tl.anim);
    drag = { c: along(e), c0: along(e), t0: e.timeStamp, samples: [[e.timeStamp, tl.raw]] };
    tipTouched();
  });
  T.el.addEventListener('pointermove', (e) => {
    if (!drag) return;
    // The scale follows the finger: dragging left, or up, moves on in time.
    const dc = along(e) - drag.c;
    drag.c = along(e);
    moveTo(tl.raw - dc / TICK);
    if (Math.abs(drag.c - drag.c0) > 6) firstInteraction('rail');
    // When the finger moved (the event's own time), not when we got to it.
    const now = e.timeStamp;
    drag.samples.push([now, tl.raw]);
    while (drag.samples.length > 2 && now - drag.samples[0][0] > 120) drag.samples.shift();
  });
  const end = (e) => {
    if (!drag) return;
    const now = e.timeStamp, d = drag;
    drag = null;
    if (Math.abs(d.c - d.c0) < 6 && now - d.t0 < 300) {
      if (now - tlTap < 320) { tlTap = 0; firstInteraction('rail'); animateTo(nearestIndex(man, Date.now()), 360); return; }
      tlTap = now; settle(); return;
    }
    const v = releaseSpeed(d, now);
    if (reduced.matches || Math.abs(v) < 0.015 || tl.raw < 0 || tl.raw > maxPos()) { settle(); return; }
    // A flick rolls on and slows to a stop, passing frames on the way: a soft
    // one a few hours, a hard one (faster swipes count for more) the whole run.
    let vel = v * (1 + 6 * Math.abs(v)), last = now;
    const step = (t) => {
      const dt = Math.min(100, t - last); last = t;
      vel *= Math.pow(0.9975, dt);
      let r = tl.raw + vel * dt;
      if (r < 0 || r > maxPos()) {
        // Run into an end: a small overshoot, then spring back.
        r = Math.max(-0.6, Math.min(maxPos() + 0.6, r)); moveTo(r); settle(); return;
      }
      moveTo(r);
      if (Math.abs(vel) > 0.003) tl.anim = requestAnimationFrame(step); else settle();
    };
    tl.anim = requestAnimationFrame(step);
  };
  T.el.addEventListener('pointerup', end);
  T.el.addEventListener('pointercancel', end);
  T.el.addEventListener('keydown', (e) => {
    if (!man) return;
    const n = maxPos(), steps = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 6, PageDown: -6 };
    let to = null;
    if (e.key in steps) to = idx + steps[e.key];
    else if (e.key === 'Home') to = 0;
    else if (e.key === 'End') to = n;
    if (to == null) return;
    e.preventDefault(); firstInteraction('rail');
    to = Math.max(0, Math.min(n, to));
    tl.raw = to; placeTrack(); setFrame(to);
  });
}

// ---- First-use tips: beside the needle, in whichever panel is showing -------------------------
const TIPS = { 1: icon('slide') + 'Slide timeline', 2: icon('reset') + 'Double-tap to reset' };
let tipShown = 0, tip2Due = false, tipFading = false;
function renderTips() {
  TL.forEach((T, i) => {
    const on = tipShown && i === (docked ? 1 : 0);
    T.tip.hidden = !on;
    if (on) { T.tip.innerHTML = TIPS[tipShown]; T.tip.toggleAttribute('data-fading', tipFading); }
  });
}
function showTip() {
  if (!store.get('nss.tip1', false)) { tipShown = 1; tipFading = false; renderTips(); }
}
function tipTouched() {
  if (tipShown === 1) { tipFading = true; renderTips(); }
  if (tipShown === 2) { tipShown = 0; store.set('nss.tip2', true); renderTips(); }
}
function scanStopped() {
  if (tipShown === 1) { tipShown = 0; store.set('nss.tip1', true); tip2Due = true; renderTips(); return; }
  if (tip2Due && !store.get('nss.tip2', false)) { tip2Due = false; tipShown = 2; tipFading = false; renderTips(); }
}

// ---- ?debug=1: where the app thinks it is, and the space the phone keeps -----------------
if (Q.has('debug')) {
  const probe = document.createElement('div');
  probe.style.cssText = 'position:fixed;visibility:hidden;padding:env(safe-area-inset-top,0px) 0 env(safe-area-inset-bottom,0px)';
  const out = document.createElement('pre');
  out.style.cssText = 'position:fixed;left:8px;top:calc(8px + env(safe-area-inset-top,0px));z-index:9;margin:0;padding:6px 8px;' +
    'background:var(--ui-display);color:var(--ui-display-ink);font:500 10px/1.4 var(--font-mono);border-radius:var(--radius-card);pointer-events:none';
  document.body.append(probe, out);
  const show = () => {
    const cs = getComputedStyle(probe), vv = window.visualViewport;
    out.textContent = [`surface ${document.documentElement.dataset.surface}${document.documentElement.hasAttribute('data-short') ? ', short' : ''}`,
      `safe top ${cs.paddingTop}, bottom ${cs.paddingBottom}`,
      `window ${innerWidth}×${innerHeight}`, vv ? `visible ${Math.round(vv.width)}×${Math.round(vv.height)}` : '',
      `screen ${screen.width}×${screen.height}`].filter(Boolean).join('\n');
  };
  show(); addEventListener('resize', show); window.visualViewport && visualViewport.addEventListener('resize', show);
}

// ---- Start -------------------------------------------------------------------------------
readTokens();
renderPanel();
setDocked(docked, true);
resize();
requestAnimationFrame(() => requestAnimationFrame(() => document.documentElement.classList.remove('still')));
document.fonts && document.fonts.ready.then(requestDraw);
document.fonts && document.fonts.load(`400 10px ${FONT}`).then(requestDraw).catch(() => {});
renderStatus();
refreshManifest();
if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('sw.js').catch(() => {});
