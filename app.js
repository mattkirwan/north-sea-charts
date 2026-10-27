/* North Sea Surf: the chart screen.

   One full-screen chart of NOAA's GFS and GFS-Wave runs, drawn here from the
   model's fields (scripts/chart_frames.py: one small gzipped grid per frame,
   on the frames branch), and one panel: the key, the band buttons, the time
   readout and the timeline. Time moves only on the timeline; the chart pans
   and zooms like a map. The design system's tokens and panel components
   (ds/) style everything; the canvas reads the same tokens. */
'use strict';

const Q = new URLSearchParams(location.search);
const FR = Q.get('frames') || 'https://raw.githubusercontent.com/mattkirwan/north-sea-charts/frames/';
const H = 3600e3, KN = 1.943844, TICK = 8, MAX_KM_ACROSS = 36;
const $ = (s) => document.querySelector(s);
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
};
const reduced = matchMedia('(prefers-reduced-motion: reduce)');

// ---- Tokens ---------------------------------------------------------------
let C = {};
function readTokens() {
  const cs = getComputedStyle(document.documentElement), v = (n) => cs.getPropertyValue(n).trim();
  C = {
    sea: v('--chart-sea'), land: v('--chart-land'), coast: v('--chart-coast'), grid: v('--chart-grid'),
    iso: v('--chart-isobar'), high: v('--chart-high'),
    height: [1, 2, 3, 4, 5, 6, 7].map((i) => v(`--height-${i}`)),
    period: [1, 2, 3, 4, 5].map((i) => v(`--period-${i}`)),
    wind: [1, 2, 3, 4, 5, 6].map((i) => v(`--wind-${i}`))
  };
}
const FONT = '"Geist Mono", ui-monospace, monospace';
const KEYS = {
  wind: { unit: 'Wind, kn', steps: ['10', '15', '20', '25', '30', '40+'], tok: 'wind', thr: [0, 15, 20, 25, 30, 40] },
  height: { unit: 'Swell height, m', steps: ['0.5', '1', '1.5', '2', '3', '4', '6+'], tok: 'height', lev: [0.5, 1, 1.5, 2, 3, 4, 6], fig: (l) => `${l} m` },
  period: { unit: 'Swell period, s', steps: ['8', '10', '12', '14', '16+'], tok: 'period', lev: [8, 10, 12, 14, 16], fig: (l) => `${l} s` }
};

// ---- State ----------------------------------------------------------------
let man = null, frames = [], idx = 0, shown = -1;
let band = store.get('nss.band', 'pressure'), swellVar = store.get('nss.swell', 'height');
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
const frameUrl = (m, i) => `${FR}f${String(m.steps[i]).padStart(m.pad || 3, '0')}.bin.gz?run=${m.run}`;
async function fetchFrame(m, i) {
  const r = await fetch(frameUrl(m, i), { mode: 'cors', credentials: 'omit' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
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
      man = m; frames = []; frames[j] = d; idx = j; tl.raw = tl.target = j; geomCache.clear();
      buildTicks(); markTick(j); setFrame(j, true);
      updatedNote = true; setTimeout(() => { updatedNote = false; renderStatus(); }, 3000);
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
const panelH = () => $('#panel').offsetHeight;
const visH = () => Math.max(100, Hs - panelH());
const kMin = () => Math.min(W, visH()) / SIDE, kMax = () => W / MAX_KM_ACROSS;
let view = store.get('nss.view', null);
function fitHome() {
  // Iceland and Svalbard down to the UK.
  const bx0 = -1450, bx1 = 1000, by0 = -760, by1 = -4480, hv = visH();
  const k = Math.min(W / (bx1 - bx0), hv / (by0 - by1)) * 0.98;
  view = { x: (bx0 + bx1) / 2, y: (by0 + by1) / 2 - (Hs - hv) / (2 * k), k };
}
function clampView() {
  const hv = visH();
  view.k = Math.max(kMin(), Math.min(kMax(), view.k));
  const k = view.k, halfW = W / (2 * k), halfH = hv / (2 * k);
  let vx = view.x, vy = view.y + (Hs - hv) / (2 * k);   // world point at the middle of the visible chart
  vx = 2 * halfW >= SIDE ? (SQ.x0 + SQ.x1) / 2 : Math.max(SQ.x0 + halfW, Math.min(SQ.x1 - halfW, vx));
  vy = 2 * halfH >= SIDE ? (SQ.y0 + SQ.y1) / 2 : Math.max(SQ.y1 + halfH, Math.min(SQ.y0 - halfH, vy));
  view.x = vx; view.y = vy - (Hs - hv) / (2 * k);
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
  p.x = e.clientX; p.y = e.clientY;
  clampView(); requestDraw(); saveView();
});
const endPtr = (e) => {
  ptrs.delete(e.pointerId);
  if (ptrs.size || !gesture) return;
  const now = performance.now(), tap = !gesture.multi && gesture.moved < 10 && now - gesture.t < 300;
  if (tap && lastTap && now - lastTap.t < 320 && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 30) {
    animateZoom(e.clientX, e.clientY, 2); lastTap = null;
  } else lastTap = tap ? { t: now, x: e.clientX, y: e.clientY } : null;
  gesture = null;
};
cv.addEventListener('pointerup', endPtr);
cv.addEventListener('pointercancel', endPtr);
cv.addEventListener('wheel', (e) => { e.preventDefault(); zoomAbout(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.002)); clampView(); requestDraw(); saveView(); }, { passive: false });
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
  const { x, y, k } = view, hv = visH();
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
  const g = pressureGeom(fi);
  world();
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  ctx.strokeStyle = C.iso; ctx.setLineDash([]); ctx.lineWidth = 1.3 / k; ctx.stroke(g.lows);
  ctx.globalAlpha = 0.85; ctx.lineWidth = 1.6 / k; ctx.setLineDash([0.1 / k, 3.5 / k]); ctx.stroke(g.highs);
  ctx.globalAlpha = 1; ctx.setLineDash([]);
  // Figures: centres first, then every third isobar, then swell band edges.
  screen();
  const boxes = [], free = (bx, by, bw, bh) => {
    if (bx < 2 || by < 2 || bx + bw > W - 2 || by + bh > hv - 4) return false;
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
  const d = frames[fi], P = man.grids.p, sq = man.square, { x, y, k } = view, hv = visH();
  const s = 32 / k, x0 = x - W / 2 / k, x1 = x + W / 2 / k, y1 = y + Hs / 2 / k, y0 = y - Hs / 2 / k;
  const paths = C.wind.map(() => new Path2D()), thr = KEYS.wind.thr;
  for (let wx = Math.ceil(x0 / s) * s; wx <= x1; wx += s) {
    for (let wy = Math.ceil(y0 / s) * s; wy <= y1; wy += s) {
      if (wx < sq.x0 || wx > sq.x1 || wy > sq.y0 || wy < sq.y1) continue;
      const px = sx(wx), py = sy(wy);
      if (py > hv + 10) continue;
      const gj = (wx - sq.x0) / (sq.x1 - sq.x0) * (P - 1), gi = (sq.y0 - wy) / (sq.y0 - sq.y1) * (P - 1);
      const u = bilinear(d.u, P, gj, gi) / 2, v = bilinear(d.v, P, gj, gi) / 2, sp = Math.hypot(u, v);
      if (sp < 0.3) continue;
      const kn = sp * KN, c = thr.reduce((m, t, i) => (kn >= t ? i : m), 0);
      const dx = u / sp, dy = -v / sp, hx = px + dx * 7, hy = py + dy * 7, p = paths[c];
      p.moveTo(px - dx * 7, py - dy * 7); p.lineTo(hx, hy);
      const a = Math.PI / 6, l = 4.5;
      p.moveTo(hx - l * (dx * Math.cos(a) - dy * Math.sin(a)), hy - l * (dy * Math.cos(a) + dx * Math.sin(a))); p.lineTo(hx, hy);
      p.lineTo(hx - l * (dx * Math.cos(a) + dy * Math.sin(a)), hy - l * (dy * Math.cos(a) - dx * Math.sin(a)));
    }
  }
  screen();
  ctx.lineWidth = 1.6; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.setLineDash([]);
  paths.forEach((p, i) => { ctx.strokeStyle = C.wind[i]; ctx.stroke(p); });
}

// ---- Panel: bands, key, swell switch --------------------------------------------------
function renderPanel() {
  document.querySelectorAll('.nss-band').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.band === band)));
  const keyrow = $('#keyrow');
  keyrow.hidden = band === 'pressure';
  $('#swellSwitch').hidden = band !== 'swell';
  $('#swellSwitch').querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.var === swellVar)));
  if (band !== 'pressure') {
    const K = KEYS[band === 'wind' ? 'wind' : swellVar];
    $('#key').setAttribute('aria-label', `${K.unit} key`);
    $('#key').innerHTML = `<span class="nss-key-unit">${K.unit}</span><div class="nss-key-steps">` +
      K.steps.map((s, i) => `<span class="nss-key-step"><i style="background: var(--${K.tok}-${i + 1})"></i>${s}</span>`).join('') + '</div>';
  }
}
document.querySelectorAll('.nss-band').forEach((b) => b.addEventListener('click', () => {
  band = b.dataset.band; store.set('nss.band', band); renderPanel(); clampView(); requestDraw();
}));
$('#swellSwitch').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  swellVar = b.dataset.var; store.set('nss.swell', swellVar); renderPanel(); requestDraw();
});

// ---- Time readout and status -------------------------------------------------------------
const fWeek = new Intl.DateTimeFormat('en-GB', { weekday: 'short' });
const fLong = new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
const fHour = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const dayName = (t) => `${fWeek.format(t)} ${new Date(t).getDate()}`;
function renderReadout() {
  if (!man) return;
  const t = validAt(man, idx);
  $('#rDay').textContent = dayName(t);
  $('#rLead').textContent = `+${man.steps[idx]}H`;
  $('#rTime').textContent = fHour.format(t);
  $('#readout').setAttribute('aria-label', `Forecast time, ${fLong.format(t)} ${fHour.format(t)}`);
}
function runName(m) { const t = m.run; return `run ${fWeek.format(t)} ${String(new Date(t).getUTCHours()).padStart(2, '0')}z`; }
function renderStatus() {
  const el = $('#rStatus');
  let text = '', warn = false;
  if (!man) text = offline ? 'Offline' : 'Loading';
  else if (!frames[idx] && !offline) text = 'Loading';
  else if (offline) text = `Offline · ${runName(man)}`;
  else if (Date.now() - man.run > 12 * H) { text = `Run ${Math.round((Date.now() - man.run) / H)} h old`; warn = true; }
  else if (updatedNote) text = `Updated to ${String(new Date(man.run).getUTCHours()).padStart(2, '0')}z`;
  el.hidden = !text; el.textContent = text;
  if (warn) el.dataset.tone = 'warn'; else delete el.dataset.tone;
}

// ---- Timeline -------------------------------------------------------------------------------
const tl = { raw: 0, target: 0, anim: 0, v: 0 };
const track = $('#track'), timeline = $('#timeline');
let ticks = [];
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
  const n = man.steps.length, now = Date.now(), html = [];
  for (let i = 0; i < n; i++) {
    const t = validAt(man, i), hr = new Date(t).getHours(), three = man.steps[i] > 120 || hr % 3 === 0;
    html.push(`<span class="nss-tick${three ? ' nss-tick--3h' : ''}${t < now ? ' nss-tick--past' : ''}${frames[i] ? '' : ' nss-tick--pending'}" style="left:${i * TICK}px"></span>`);
  }
  const first = new Date(validAt(man, 0)); first.setHours(24, 0, 0, 0);
  for (let d = new Date(first); d.getTime() <= validAt(man, n - 1); d.setDate(d.getDate() + 1)) {
    const p = fracIndex(d.getTime()) * TICK, past = d.getTime() < now ? ' nss-day--past' : '';
    html.push(`<span class="nss-tick nss-tick--day${past ? ' nss-tick--past' : ''}" style="left:${p.toFixed(1)}px"></span><span class="nss-day${past}" style="left:${p.toFixed(1)}px">${dayName(d.getTime())}</span>`);
  }
  const np = fracIndex(now);
  if (np >= -0.5 && np <= n - 0.5) html.push(`<span class="nss-tick nss-tick--now" style="left:${(np * TICK).toFixed(1)}px"></span>`);
  html.push(`<span class="nss-end" style="left:${(n - 1) * TICK + 4}px"></span>`);
  track.innerHTML = html.join('');
  ticks = [...track.querySelectorAll('.nss-tick:not(.nss-tick--day):not(.nss-tick--now)')];
  timeline.setAttribute('aria-valuemax', String(n - 1));
  placeTrack();
}
setInterval(buildTicks, 5 * 60e3);
function markTick(i) { if (ticks[i]) ticks[i].classList.remove('nss-tick--pending'); }
const maxPos = () => (man ? man.steps.length - 1 : 0);
function shownPos() {
  // Past either end, the scale stretches a little and springs back.
  const r = tl.raw, m = maxPos(), over = r < 0 ? r : r > m ? r - m : 0;
  return over ? (over < 0 ? 0 : m) + Math.sign(over) * (1 - 1 / (1 + Math.abs(over) * 0.35)) * 4 : r;
}
function placeTrack() { track.style.transform = `translateX(${(-shownPos() * TICK).toFixed(2)}px)`; }
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
  timeline.setAttribute('aria-valuenow', String(i));
  timeline.setAttribute('aria-valuetext', `${fLong.format(t)}, ${fHour.format(t)}`);
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
timeline.addEventListener('pointerdown', (e) => {
  if (!man) return;
  timeline.setPointerCapture(e.pointerId);
  cancelAnimationFrame(tl.anim);
  drag = { x: e.clientX, x0: e.clientX, t0: performance.now(), samples: [[performance.now(), tl.raw]] };
  tipTouched();
});
timeline.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.x;
  drag.x = e.clientX;
  moveTo(tl.raw - dx / TICK);
  const now = performance.now();
  drag.samples.push([now, tl.raw]);
  while (drag.samples.length > 2 && now - drag.samples[0][0] > 100) drag.samples.shift();
});
const tlEnd = () => {
  if (!drag) return;
  const now = performance.now(), d = drag;
  drag = null;
  if (Math.abs(d.x - d.x0) < 6 && now - d.t0 < 300) {
    if (now - tlTap < 320) { tlTap = 0; animateTo(nearestIndex(man, Date.now()), 360); return; }
    tlTap = now; settle(); return;
  }
  const [t0, r0] = d.samples[0], v = now - t0 > 0 ? (tl.raw - r0) / (now - t0) : 0;   // frames per ms
  if (reduced.matches || Math.abs(v) < 0.01 || tl.raw < 0 || tl.raw > maxPos()) { settle(); return; }
  // A flick carries on and slows to a stop, passing frames on the way.
  let vel = v, last = now;
  const step = (t) => {
    const dt = Math.min(40, t - last); last = t;
    vel *= Math.pow(0.9965, dt);
    let r = tl.raw + vel * dt;
    if (r < -1.5 || r > maxPos() + 1.5) { r = Math.max(-1.5, Math.min(maxPos() + 1.5, r)); vel = 0; }
    moveTo(r);
    if (Math.abs(vel) > 0.004) tl.anim = requestAnimationFrame(step); else settle();
  };
  tl.anim = requestAnimationFrame(step);
};
timeline.addEventListener('pointerup', tlEnd);
timeline.addEventListener('pointercancel', tlEnd);
timeline.addEventListener('keydown', (e) => {
  if (!man) return;
  const n = maxPos(), steps = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 6, PageDown: -6 };
  let to = null;
  if (e.key in steps) to = idx + steps[e.key];
  else if (e.key === 'Home') to = 0;
  else if (e.key === 'End') to = n;
  if (to == null) return;
  e.preventDefault();
  to = Math.max(0, Math.min(n, to));
  tl.raw = to; placeTrack(); setFrame(to);
});

// ---- First-use tips -----------------------------------------------------------------------
const tipEl = $('#tip');
const TIPS = {
  1: '<svg aria-hidden="true" width="18" height="10" viewBox="0 0 24 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M1 6h22M5 2 1 6l4 4M19 2l4 4-4 4"></path></svg>Slide timeline',
  2: '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="10" cy="10" r="3"></circle><circle cx="10" cy="10" r="7" stroke-dasharray="2.5 2.5"></circle></svg>Double-tap to reset'
};
let tipShown = 0, tip2Due = false;
function showTip() {
  if (!store.get('nss.tip1', false)) { tipShown = 1; tipEl.innerHTML = TIPS[1]; tipEl.hidden = false; delete tipEl.dataset.fading; }
}
function tipTouched() {
  if (tipShown === 1) tipEl.dataset.fading = '';
  if (tipShown === 2) { tipEl.hidden = true; tipShown = 0; store.set('nss.tip2', true); }
}
function scanStopped() {
  if (tipShown === 1) { tipEl.hidden = true; tipShown = 0; store.set('nss.tip1', true); tip2Due = true; return; }
  if (tip2Due && !store.get('nss.tip2', false)) {
    tip2Due = false; tipShown = 2; tipEl.innerHTML = TIPS[2]; tipEl.hidden = false; delete tipEl.dataset.fading;
  }
}

// ---- Start -------------------------------------------------------------------------------
readTokens();
renderPanel();
resize();
document.fonts && document.fonts.ready.then(requestDraw);
document.fonts && document.fonts.load(`400 10px ${FONT}`).then(requestDraw).catch(() => {});
renderStatus();
refreshManifest();
if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('sw.js').catch(() => {});
