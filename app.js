/* North Sea Surf: the chart screen.

   One full-screen chart of NOAA's GFS and GFS-Wave runs, drawn here from the
   model's fields (scripts/chart_frames.py: one small gzipped grid per frame,
   on the frames branch), and one panel: the key, the band buttons, the time
   readout and the timeline. The panel is either open along the bottom or
   docked to a narrow column at the side (Menu › Settings › Panel), on the
   right or the left (› Hand); both are in the page, one shown.
   Time moves only on the timeline; the chart pans and zooms like a map. The
   design system's tokens, panel components and icons (ds/) style
   everything; the canvas reads the same tokens. The words are in the
   languages of the North Sea's coasts (i18n.js), one at a time (› Language). */
'use strict';

const Q = new URLSearchParams(location.search);
// This deploy's commit (index.html's ?v=, stamped by deploy.yml), for feedback.
const VERSION = new URL(document.currentScript.src).searchParams.get('v') || 'dev';
const FR = Q.get('frames') || 'https://raw.githubusercontent.com/mattkirwan/north-sea-charts/frames/';
const H = 3600e3, MPH = 2.236936, TICK = 8, MAX_KM_ACROSS = 36;
const $ = (s) => document.querySelector(s);
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
};
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
// Usage stats (Umami, loaded by index.html): the first thing someone does
// beyond looking, once a visit: pan, zoom, rail (the timeline), play or band.
let interacted = false;
try { interacted = !!sessionStorage.getItem('nss_fi'); } catch {}
function firstInteraction(type) {
  if (interacted) return;
  interacted = true;
  try { sessionStorage.setItem('nss_fi', '1'); } catch {}
  if (window.umami) umami.track('first_interaction', { type });
}

// ---- Language -------------------------------------------------------------
// The phone's own, if it's one of ours (Norwegian under any of its names),
// else English, until someone picks one (Menu › Settings › Language, or on
// first open).
function phoneLang() {
  for (const l of navigator.languages || [navigator.language]) {
    const p = String(l || '').toLowerCase().split('-')[0];
    const c = p === 'no' || p === 'nn' ? 'nb' : p === 'fy' ? 'nl' : p;
    if (LANGS[c]) return c;
  }
  return 'en';
}
let lang = store.get('nss.lang', null);
const langAsked = LANGS[lang] != null;
if (!langAsked) lang = phoneLang();
const tr = (k, vars) => {
  const s = LANGS[lang].t[k] ?? LANGS.en.t[k];
  return vars ? s.replace(/\{(\w+)\}/g, (m, v) => vars[v]) : s;
};
let fWeek, fLong, fHour;
function applyLang() {
  const tag = LANGS[lang].tag;
  document.documentElement.lang = tag;
  fWeek = new Intl.DateTimeFormat(tag, { weekday: 'short' });
  fLong = new Intl.DateTimeFormat(tag, { weekday: 'long', day: 'numeric', month: 'long' });
  fHour = new Intl.DateTimeFormat(tag, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  document.querySelectorAll('[data-t]').forEach((el) => { el.textContent = tr(el.dataset.t); });
  document.querySelectorAll('[data-t-label]').forEach((el) => el.setAttribute('aria-label', tr(el.dataset.tLabel)));
  document.querySelectorAll('[data-lang-name]').forEach((el) => { el.textContent = LANGS[lang].name; });
}
applyLang();

// ---- Tokens ---------------------------------------------------------------
let C = {};
function readTokens() {
  const cs = getComputedStyle(document.documentElement), v = (n) => cs.getPropertyValue(n).trim();
  C = {
    sea: v('--chart-sea'), land: v('--chart-land'), coast: v('--chart-coast'), grid: v('--chart-grid'),
    iso: v('--chart-isobar'), high: v('--chart-high'), arrow: v('--chart-arrow'), ice: v('--chart-ice'),
    ink: v('--ui-ink'), control: v('--ui-control'), raised: v('--ui-raised'),
    height: KEYS.height.lev.map((l, i) => v(keyTok(KEYS.height, i))),
    period: KEYS.period.lev.map((l, i) => v(keyTok(KEYS.period, i))),
    wind: KEYS.wind.lev.map((l, i) => v(keyTok(KEYS.wind, i)))
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
  menu: '<path d="M4 6.5 H20 M4 12 H20 M4 17.5 H14"></path>',
  close: '<path d="M6 6 L18 18 M18 6 L6 18"></path>',
  back: '<path d="M14.5 6 L8.5 12 L14.5 18"></path>',
  chevron: '<path d="M9.5 6 L15.5 12 L9.5 18"></path>',
  'panel-bottom': '<rect x="3" y="4.5" width="18" height="15"></rect><path d="M3 14.5 H21"></path>',
  'panel-side': '<rect x="3" y="4.5" width="18" height="15"></rect><path d="M15.5 4.5 V19.5"></path>',
  check: '<path d="M5 12.5 L10 17.5 L19 7"></path>',
  play: '<path class="nss-play-icon" d="M8 5.5 L18.5 12 L8 18.5 Z"></path>',
  pause: '<path d="M8.5 5.5 V18.5 M15.5 5.5 V18.5" stroke-width="2.2"></path>',
  share: '<path d="M12 3.5 V14"></path><path d="M8 7.5 L12 3.5 L16 7.5"></path><path d="M5.5 11 V20 H18.5 V11"></path>',
  target: '<path d="M12 3 V8.5 M12 15.5 V21 M3 12 H8.5 M15.5 12 H21"></path><rect x="8.5" y="8.5" width="7" height="7"></rect>'
};
const icon = (n, cls = '') => `<svg class="nss-icon${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n]}</svg>`;
document.querySelectorAll('[data-icon]').forEach((el) => { el.insertAdjacentHTML('afterbegin', icon(el.dataset.icon, el.dataset.iconSize ? ` nss-icon--${el.dataset.iconSize}` : '')); });
// The keys: 13 stepped bins each, every token named for the bottom of its
// bin (wind-10 is 10 to 15 mph), from calm, flat and chop up, so every sea
// cell under them takes a key colour. Height's are named in centimetres, as
// a CSS name can't hold a decimal point (height-150 is 1.5 to 2 m).
const bins = (top, step) => Array.from({ length: top / step + 1 }, (_, i) => i * step);
const KEYS = {
  wind: { unit: 'windUnit', tok: 'wind', lev: bins(60, 5) },
  height: { unit: 'heightUnit', tok: 'height', lev: bins(6, 0.5), cm: true, fig: (l) => `${l} m` },
  period: { unit: 'periodUnit', tok: 'period', lev: bins(24, 2), fig: (l) => `${l} s` }
};
const keyTok = (K, i) => `--${K.tok}-${K.cm ? Math.round(K.lev[i] * 100) : K.lev[i]}`;
// Which of a key's steps a value falls in (the top one past its end, -1
// below the first or for no value): a value on a boundary is the upper bin.
function bin(K, v) {
  if (!(v >= K.lev[0])) return -1;
  let i = 0;
  while (i < K.lev.length - 1 && v >= K.lev[i + 1]) i++;
  return i;
}
const binColour = (K, v) => C[K.tok][Math.max(0, bin(K, v))];

// ---- State ----------------------------------------------------------------
let man = null, frames = [], idx = 0, shown = -1;
let band = store.get('nss.band', 'pressure'), swellVar = store.get('nss.swell', 'height');
let docked = store.get('nss.docked', false), hand = store.get('nss.hand', 'right');
// Beacons: the grid points on the chart, and every layer off, beside the
// band (which comes back when it goes off). Kept between visits.
let beaconsOn = store.get('nss.beacons', false);
let offline = false, updatedNote = false, failedAt = {};
// The bins found in the run's frames loaded so far (the keys' steps).
let present = { wind: [], height: [], period: [] };
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
// the frames at the top of the branch.) The frames themselves come from
// m.base (Cloudflare R2) when the manifest names it, else the branch.
const frameUrl = (m, i) => `${m.base || FR}${m.dir ? m.dir + '/' : ''}f${String(m.steps[i]).padStart(m.pad || 3, '0')}.bin.gz?run=${m.run}`;
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
      markTick(i); notePresent(d);
      if (i === idx) requestDraw();
      if (Math.abs(i - idx) <= 8) warm();
    }).catch(() => { failedAt[i] = Date.now(); if (!navigator.onLine) offline = true; })
      .finally(() => { loading.delete(i); inflight--; renderStatus(); if (m === man) pump(); });
  }
}
setInterval(pump, 15e3);
// A frame's bins into the run's; the key redrawn when that grows.
let presentT = 0;
function notePresent(d) {
  let grew = false;
  const mark = (K, v) => { const b = bin(K, v); if (b >= 0 && !present[K.tok][b]) { present[K.tok][b] = true; grew = true; } };
  const ws = man.scale.wind || 2, sh = man.scale.h, st = man.scale.t;
  for (let k = 0; k < d.u.length; k++) mark(KEYS.wind, Math.hypot(d.u[k], d.v[k]) / ws * MPH);
  for (let k = 0; k < d.h.length; k++) if (d.h[k] !== 255) mark(KEYS.height, d.h[k] / sh);
  for (let k = 0; k < d.t.length; k++) if (d.t[k] !== 255) mark(KEYS.period, d.t[k] / st);
  if (grew) { clearTimeout(presentT); presentT = setTimeout(renderPanel, 200); }
}

// ---- Manifest and new runs ----------------------------------------------------
async function getManifest() {
  const r = await fetch(`${FR}manifest.json?t=${Math.floor(Date.now() / 60e3)}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
// The sea ice: one chart a day, the same on every band (ice.json beside the
// manifest), as concentration classes of rings in the square's km.
let ice = null;
async function loadIce(m) {
  if (!m.ice) { ice = null; return; }
  if (ice && ice.date === m.ice.date) return;
  try {
    const r = await fetch(`${FR}${m.ice.file}?d=${m.ice.date}`, { mode: 'cors', credentials: 'omit' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    ice = {
      date: j.date,
      classes: j.classes.map((c) => {
        const rings = c.rings.map((a) => {
          const out = new Float64Array(a.length);
          let x = 0, y = 0;
          for (let k = 0; k < a.length; k += 2) { x += a[k]; y += a[k + 1]; out[k] = x * j.unit; out[k + 1] = y * j.unit; }
          return out;
        });
        return { alpha: 0.3 + 0.6 * c.t / 10, path: pathOf(rings, true) };
      })
    };
    requestDraw();
  } catch {}
}
const validAt = (m, i) => m.run + m.steps[i] * H;
function nearestIndex(m, t) {
  let best = 0;
  for (let i = 1; i < m.steps.length; i++) if (Math.abs(validAt(m, i) - t) < Math.abs(validAt(m, best) - t)) best = i;
  return best;
}
// The grid (grid.js): NOAA's own cells and the run's cell tiles. Nothing
// shows them yet but the ?debug=1 readout.
let grid = null;
function makeGrid(m) {
  try {
    return NSSGrid.fromManifest(m, {
      base: m.base || FR,
      get: async (url) => {
        const r = await fetch(url, { mode: 'cors', credentials: 'omit' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return gunzip(await r.arrayBuffer());
      }
    });
  } catch { return null; }
}
async function refreshManifest() {
  let m;
  // A manifest from the phone's own copy still counts as offline.
  try { m = await getManifest(); offline = navigator.onLine === false; } catch { offline = true; renderStatus(); return; }
  if (!man) {
    man = m; frames = []; loadIce(m); grid = makeGrid(m);
    present = { wind: [], height: [], period: [] };
    idx = nearestIndex(m, Date.now());
    tl.raw = tl.target = idx;
    buildTicks(); setFrame(idx, true); pump(); hintWait(); openAt();
  } else if (m.run > man.run) {
    // Keep the needle on the same valid time: load that frame of the new run first, then swap.
    const t = validAt(man, idx), j = nearestIndex(m, t);
    try {
      const d = await fetchFrame(m, j);
      man = m; frames = []; loadIce(m); grid = makeGrid(m); frames[j] = d;
      present = { wind: [], height: [], period: [] }; notePresent(d); failedAt = {}; idx = j; tl.raw = tl.target = play.pos = j; geomCache.clear();
      if (beacon) loadBeacon();
      buildTicks(); markTick(j); setFrame(j, true);
      updatedNote = true; setTimeout(fadeUpdated, 3000);
      pump(); hintWait();
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

// ---- Saltburn's swell window ----------------------------------------------------------
// The open sea swell can cross to reach Saltburn, which beacons are for:
// km of sea along each bearing from just off the pier to the first land,
// and the three bends (round the Aberdeenshire corner, along the Yorkshire
// coast, through the gap between Orkney and Shetland), each from its own
// point over its own fan. Geography, so kept here (assets/window.json, as
// scripts/swell_sources.py's swell_window() makes it, which the chart job
// also publishes as window.json); remake it if that changes.
let swellWin = null;
fetch('assets/window.json').then((r) => r.json()).then((w) => { swellWin = w; requestDraw(); }).catch(() => { swellWin = false; requestDraw(); });
function gcAway(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180, f1 = lat1 * r, f2 = lat2 * r, dl = (lon2 - lon1) * r;
  const km = 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(Math.sin((f2 - f1) / 2) ** 2 + Math.cos(f1) * Math.cos(f2) * Math.sin(dl / 2) ** 2)));
  const b = (Math.atan2(Math.sin(dl) * Math.cos(f2), Math.cos(f1) * Math.sin(f2) - Math.sin(f1) * Math.cos(f2) * Math.cos(dl)) / r + 360) % 360;
  return { km, b };
}
// In the window (or one of its bends), or true if the window didn't load.
function inWindow(lat, lon) {
  const w = swellWin;
  if (!w) return swellWin === false;
  const at = (reach, b) => reach[Math.round(b / w.step) % reach.length];
  const o = gcAway(w.origin[0], w.origin[1], lat, lon);
  if (o.km <= at(w.reach, o.b)) return true;
  return w.bends.some((g) => {
    const e = gcAway(g.lat, g.lon, lat, lon), r = at(g.reach, e.b);
    return r > 0 && e.km >= (g.start || 0) && e.km <= r;
  });
}

// ---- View: pan and zoom -------------------------------------------------------------
const cv = $('#chart'), ctx = cv.getContext('2d');
let W = 0, Hs = 0, dpr = 1;
const SQ = { x0: -2805, x1: 1795, y0: -650, y1: -5250 }, SIDE = 4600;
const COL_W = 64;
const panelH = () => $('#panel').offsetHeight;
// The docked column is in use: docked, and no beacon open (its sheet is always
// the open panel, along the bottom).
const sideOn = () => docked && !beacon;
// The part of the screen the chart has to itself, from x across: above the
// open panel, or beside the docked column.
const vis = () => (sideOn() ? { x: hand === 'left' ? COL_W : 0, w: Math.max(100, W - COL_W), h: Hs } : { x: 0, w: W, h: Math.max(100, Hs - panelH()) });
// Everything between x0 and x1 and below y is under the panel.
const panelBox = () => (!sideOn() ? { x0: 0, x1: W, y: Hs - panelH() }
  : { x0: hand === 'left' ? 0 : W - COL_W, x1: hand === 'left' ? COL_W : W, y: $('#column').offsetTop });
const kMin = () => { const v = vis(); return Math.min(v.w, v.h) / SIDE; }, kMax = () => W / MAX_KM_ACROSS;
let view = store.get('nss.view', null);
function fitHome() {
  // Iceland and Svalbard down to the UK.
  const bx0 = -1450, bx1 = 1000, by0 = -760, by1 = -4480, v = vis();
  const k = Math.min(v.w / (bx1 - bx0), v.h / (by0 - by1)) * 0.98;
  view = { x: (bx0 + bx1) / 2 - (v.x + v.w / 2 - W / 2) / k, y: (by0 + by1) / 2 - (Hs - v.h) / (2 * k), k };
}
function clampView() {
  const v = vis();
  view.k = Math.max(kMin(), Math.min(kMax(), view.k));
  const k = view.k, halfW = v.w / (2 * k), halfH = v.h / (2 * k), ox = (v.x + v.w / 2 - W / 2) / k, oy = (Hs - v.h) / (2 * k);
  let vx = view.x + ox, vy = view.y + oy;   // world point at the middle of the visible chart
  vx = 2 * halfW >= SIDE ? (SQ.x0 + SQ.x1) / 2 : Math.max(SQ.x0 + halfW, Math.min(SQ.x1 - halfW, vx));
  vy = 2 * halfH >= SIDE ? (SQ.y0 + SQ.y1) / 2 : Math.max(SQ.y1 + halfH, Math.min(SQ.y0 - halfH, vy));
  view.x = vx - ox; view.y = vy - oy;
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
  requestDraw(); renderHint(); fitKeys();
  if (guideOn()) placeGuide();
}
addEventListener('resize', resize);

const ptrs = new Map();
let gesture = null, lastTap = null, zoomAnim = 0, onTap = null;
cv.addEventListener('pointerdown', (e) => {
  cv.setPointerCapture(e.pointerId);
  ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
  cancelAnimationFrame(zoomAnim); cancelAnimationFrame(glideAnim); beaconsGlide = false;
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
    animateZoom(e.clientX, e.clientY, 2); lastTap = null; firstInteraction('zoom'); emit('map.zoom');
  } else {
    lastTap = tap ? { t: now, x: e.clientX, y: e.clientY } : null;
    if (tap && onTap) onTap(e.clientX, e.clientY);
  }
  if (gesture.multi) emit('map.zoom');
  gesture = null;
};
cv.addEventListener('pointerup', endPtr);
cv.addEventListener('pointercancel', endPtr);
cv.addEventListener('wheel', (e) => { e.preventDefault(); cancelAnimationFrame(glideAnim); beaconsGlide = false; firstInteraction('zoom'); emit('map.zoom'); zoomAbout(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.002)); clampView(); requestDraw(); saveView(); }, { passive: false });
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
// What the chart shows: the selected band; or, with a beacon open, every
// layer its toggles have on, each its own kind of mark: swell (always its
// height) the fill, pressure the lines, wind the arrows at the grid points,
// with its slate field only when there's no swell fill.
function layersOn() {
  if (beacon) return { ...beacon.layers, swellVar: 'height', field: beacon.layers.wind && !beacon.layers.swell, points: beacon.layers.wind };
  if (beaconsOn) return { pressure: false, wind: false, swell: false, swellVar, field: false, points: false };
  return { pressure: band === 'pressure', wind: band === 'wind', swell: band === 'swell', swellVar, field: band === 'wind', points: false };
}
// The geometry the chart needs for a frame, as [cache key, build].
function geomParts(i) {
  const L = layersOn(), r = man.run, out = [];
  if (L.swell) out.push([`${L.swellVar}${r}:${i}`, () => swellGeom(i, L.swellVar)]);
  if (L.field) out.push([`wind${r}:${i}`, () => windGeom(i)]);
  if (L.pressure) out.push([`p${r}:${i}`, () => pressureGeom(i)]);
  return out;
}
const geomReady = (i) => geomParts(i).every(([key]) => geomCache.has(key));
const buildGeom = (i) => geomParts(i).forEach(([key, make]) => { if (!geomCache.has(key)) make(); });
// While the timeline moves, the frame to draw. Building one takes a phone tens
// of ms, too long for every frame a drag or flick passes: the needle's own
// frame is built at most every 150 ms and every few redraws, and in between
// the chart shows the nearest one already built, and catches up when the
// timeline stops.
let lastBuild = 0, sinceBuild = 0;
function movingFrame(fi) {
  if (fi < 0 || !tl.moving || geomReady(fi)) return fi;
  if (performance.now() - lastBuild > 150 && sinceBuild >= 4) return fi;
  for (let d = 1; d < man.steps.length; d++) {
    for (const i of [fi - d, fi + d]) if (frames[i] && geomReady(i)) { requestDraw(); return i; }
  }
  return fi;
}
function draw() {
  drawQueued = false;
  if (!W) return;
  const { x, y, k } = view, pb = panelBox();
  checkBeaconsReach();
  const world = () => ctx.setTransform(dpr * k, 0, 0, -dpr * k, dpr * (W / 2 - x * k), dpr * (Hs / 2 + y * k));
  const screen = () => ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const sx = (wx) => W / 2 + (wx - x) * k, sy = (wy) => Hs / 2 - (wy - y) * k;
  screen();
  // No default sea under Wind or Swell: every sea cell takes a key
  // colour there, and where the model has none it reads as land.
  // (Beyond the model's square, the plain sea as ever.)
  const L = layersOn();
  ctx.fillStyle = C.sea; ctx.fillRect(0, 0, W, Hs);
  if (L.field || L.swell) {
    ctx.fillStyle = C.land;
    ctx.fillRect(sx(SQ.x0), sy(SQ.y0), (SQ.x1 - SQ.x0) * k, (SQ.y0 - SQ.y1) * k);
  }
  const fi = movingFrame(frames[idx] ? idx : shown >= 0 && frames[shown] ? shown : -1);
  if (fi >= 0) shown = fi;
  if (fi >= 0 && !geomReady(fi)) {
    buildGeom(fi); lastBuild = performance.now(); sinceBuild = 0;
    if (tlDbg && tlDbg.cur && tl.moving) tlDbg.cur.builds++;
  } else sinceBuild++;
  const swell = L.swell && fi >= 0 ? swellGeom(fi, L.swellVar) : null;
  if (swell) {
    world();
    const cols = C[KEYS[L.swellVar].tok];
    swell.bands.forEach((b, i) => { ctx.fillStyle = cols[i]; ctx.fill(b.path, 'evenodd'); });
  }
  if (L.field && fi >= 0) {
    world();
    windGeom(fi).forEach((p, i) => { ctx.fillStyle = C.wind[i]; ctx.fill(p, 'evenodd'); });
  }
  if (ice) {
    // Sea ice on every band: under the land and the weather, over the sea colours.
    world();
    ctx.lineJoin = 'round'; ctx.strokeStyle = C.ice; ctx.fillStyle = C.ice; ctx.lineWidth = 0.8 / k;
    for (const c of ice.classes) {
      ctx.globalAlpha = c.alpha; ctx.fill(c.path, 'evenodd');
      ctx.globalAlpha = 0.9; ctx.stroke(c.path);
    }
    ctx.globalAlpha = 1;
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
  if (fi < 0) { screen(); drawCrosses(sx, sy, pb, L, -1); placeCrossSpot(); placeBeacon(); return; }
  if (L.wind && !L.points) drawWind(fi, sx, sy, screen);
  // Isobars, centres and their figures: on the Pressure band, or with a beacon's pressure on.
  const g = L.pressure ? pressureGeom(fi) : { centres: [], labelled: [] };
  if (g.lows) {
  world();
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  ctx.strokeStyle = C.iso; ctx.setLineDash([]); ctx.lineWidth = 1.3 / k; ctx.stroke(g.lows);
  ctx.globalAlpha = 0.85; ctx.lineWidth = 1.6 / k; ctx.setLineDash([0.1 / k, 3.5 / k]); ctx.stroke(g.highs);
  ctx.globalAlpha = 1; ctx.setLineDash([]);
  }
  // The grid points a beacon can go on, over the weather, under the figures.
  screen();
  drawCrosses(sx, sy, pb, L, fi); placeCrossSpot();
  // Figures: centres first, then every third isobar, then swell band edges.
  const boxes = [], free = (bx, by, bw, bh) => {
    if (bx < 2 || by < 2 || bx + bw > W - 2 || by + bh > Hs - 2) return false;
    if (bx + bw > pb.x0 - 4 && bx < pb.x1 + 4 && by + bh > pb.y - 4) return false;
    if (boxes.some((o) => bx < o[0] + o[2] && o[0] < bx + bw && by < o[1] + o[3] && o[1] < by + bh)) return false;
    boxes.push([bx, by, bw, bh]); return true;
  };
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for (const c of g.centres) {
    const px = sx(c.x), py = sy(c.y), col = c.low ? C.iso : C.high;
    if (!free(px - 16, py - 14, 32, 38)) continue;
    ctx.font = `600 22px ${FONT}`; halo(tr(c.low ? 'low' : 'high'), px, py - 2, col, C.sea);
    ctx.font = `400 10px ${FONT}`; halo(String(c.val), px, py + 16, col, C.sea);
  }
  ctx.font = `400 10px ${FONT}`;
  for (const l of g.labelled) placeAlong(l.pts, String(l.lev), 70, 260, sx, sy, free, (t, px, py) => halo(t, px, py, C.iso, C.sea));
  if (swell) {
    const cols = C[KEYS[L.swellVar].tok];
    swell.bands.forEach((b, i) => {
      const text = KEYS[L.swellVar].fig(b.lev);
      if (!b.lev) return;
      for (const r of b.rings) placeAlong(r, text, 200, 520, sx, sy, (bx, by, bw, bh) => {
        const wx = x + (bx + bw / 2 - W / 2) / k, wy = y - (by + bh / 2 - Hs / 2) / k;
        return nearSea(swell, wx, wy) && free(bx, by, bw, bh);
      }, (t, px, py) => halo(t, px, py, C.iso, cols[i]));
    });
  }
  placeBeacon();
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
// A wind arrow, 14 px, centred on (px, py), pointing the way (dx, dy) on screen.
function arrowAt(p, px, py, dx, dy) {
  const hx = px + dx * 7, hy = py + dy * 7, a = Math.PI / 6, l = 4.5;
  p.moveTo(px - dx * 7, py - dy * 7); p.lineTo(hx, hy);
  p.moveTo(hx - l * (dx * Math.cos(a) - dy * Math.sin(a)), hy - l * (dy * Math.cos(a) + dx * Math.sin(a))); p.lineTo(hx, hy);
  p.lineTo(hx - l * (dx * Math.cos(a) + dy * Math.sin(a)), hy - l * (dy * Math.cos(a) - dx * Math.sin(a)));
}
function drawWind(fi, sx, sy, screen) {
  const d = frames[fi], P = man.grids.p, sq = man.square, { x, y, k } = view, pb = panelBox();
  const s = 32 / k, x0 = x - W / 2 / k, x1 = x + W / 2 / k, y1 = y + Hs / 2 / k, y0 = y - Hs / 2 / k;
  const path = new Path2D(), ws = man.scale.wind || 2;
  for (let wx = Math.ceil(x0 / s) * s; wx <= x1; wx += s) {
    for (let wy = Math.ceil(y0 / s) * s; wy <= y1; wy += s) {
      if (wx < sq.x0 || wx > sq.x1 || wy > sq.y0 || wy < sq.y1) continue;
      const px = sx(wx), py = sy(wy);
      if (px > pb.x0 + 10 && px < pb.x1 - 10 && py > pb.y + 10) continue;
      const gj = (wx - sq.x0) / (sq.x1 - sq.x0) * (P - 1), gi = (sq.y0 - wy) / (sq.y0 - sq.y1) * (P - 1);
      const u = bilinear(d.u, P, gj, gi) / ws, v = bilinear(d.v, P, gj, gi) / ws, sp = Math.hypot(u, v);
      if (sp < 0.3) continue;
      arrowAt(path, px, py, u / sp, -v / sp);
    }
  }
  screen();
  ctx.lineWidth = 1.6; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.setLineDash([]);
  ctx.strokeStyle = C.arrow; ctx.stroke(path);
}

// ---- Panel: bands, key, swell switch, open or docked, right or left -------------------------
const panelEl = $('#panel'), columnEl = $('#column'), flyout = $('#flyout');
function renderPanel() {
  document.querySelectorAll('.nss-band[data-band]').forEach((b) => b.setAttribute('aria-pressed', String(!beaconsOn && b.dataset.band === band)));
  document.querySelectorAll('[data-beacons]').forEach((b) => b.setAttribute('aria-pressed', String(beaconsOn)));
  // No layers on, so no key.
  $('#keyslot').toggleAttribute('data-off', beaconsOn);
  document.querySelectorAll('[data-swell]').forEach((sw) => {
    sw.hidden = band !== 'swell';
    sw.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.var === swellVar)));
  });
  let unit, html;
  if (band === 'pressure') {
    // The two isobar styles, drawn as the chart draws them.
    const line = (attrs) => `<i class="key-line"><svg aria-hidden="true"><line x1="2" y1="3" x2="92%" y2="3" style="stroke: var(--chart-isobar)" ${attrs}></line></svg></i>`;
    unit = tr('isobars');
    html = `<span class="nss-key-unit">${unit}</span><div class="nss-key-steps">` +
      `<span class="nss-key-step">${line('stroke-width="1.3"')}${tr('roundLows')}</span>` +
      `<span class="nss-key-step">${line('stroke-width="1.6" stroke-linecap="round" stroke-dasharray="0.1 3.5" opacity="0.85"')}${tr('roundHighs')}</span></div>`;
  } else {
    const K = KEYS[band === 'wind' ? 'wind' : swellVar];
    unit = tr(K.unit);
    // Only the bins found in the run loaded so far (all of them before any
    // is), so the key holds still while the time moves.
    const steps = K.lev.map((l, i) => [i, `${l}${i === K.lev.length - 1 ? '+' : ''}`]).filter(([i]) => !present[K.tok].some(Boolean) || present[K.tok][i]);
    html = `<span class="nss-key-unit">${unit}</span><div class="nss-key-steps">` +
      steps.map(([i, t]) => `<span class="nss-key-step"${i % 2 ? ' data-odd' : ''}><i style="background: var(${keyTok(K, i)})"></i>${t}</span>`).join('') + '</div>';
  }
  document.querySelectorAll('[data-key]').forEach((k) => { k.setAttribute('aria-label', tr('keyOf', { unit })); k.innerHTML = html; });
  fitKeys();
  // Docked, the key floats level with the selected band (and comes in from
  // the column each time it moves).
  const slot = columnEl.querySelector(`.nss-band[data-band="${band}"]`).parentNode;
  if (flyout.parentNode !== slot) slot.appendChild(flyout);
  flyout.hidden = beaconsOn;
  renderHint();
}
// A key too narrow for all its figures (13 steps beside the swell switch)
// keeps every swatch but labels every other bin of the scale: 0, 1, 2 m;
// 0, 10, 20 mph; 0, 4, 8 s.
function fitKeys() {
  document.querySelectorAll('[data-key]').forEach((k) => {
    k.removeAttribute('data-sparse');
    // A figure needs its own width and 4 px clear of the next.
    const r = document.createRange(), tight = [...k.querySelectorAll('.nss-key-step')].some((s) => {
      if (!s.clientWidth || !s.lastChild) return false;
      r.selectNodeContents(s.lastChild);
      return r.getBoundingClientRect().width + 4 > s.getBoundingClientRect().width + 1;
    });
    if (tight) k.setAttribute('data-sparse', '');
  });
}
function setBand(b) {
  band = b; store.set('nss.band', band);
  if (beaconsOn) { beaconsOn = false; store.set('nss.beacons', false); }
  renderPanel(); requestDraw(); warm();
  // The open panel grows or shrinks with the key row: settle the map after.
  if (!sideOn()) setTimeout(easeClamp, reduced.matches ? 0 : 220);
}
document.querySelectorAll('.nss-band[data-band]').forEach((b) => b.addEventListener('click', () => {
  if (band === b.dataset.band && !beaconsOn) return;
  firstInteraction('band'); setBand(b.dataset.band);
}));
// Beacons on: the layers off, the grid points on, zoomed in to where they
// can be used; off: the band from before, the map left where it is.
// It's there to switch from beacons' minimum zoom in (the button is greyed
// further out), so the map stays put; only the new-feature card's Show me
// glides in first.
function setBeacons(on, zoom) {
  beaconsOn = on; store.set('nss.beacons', on);
  renderPanel(); requestDraw(); warm();
  if (!sideOn()) setTimeout(easeClamp, reduced.matches ? 0 : 220);
  if (on) { if (zoom) zoomToBeacons(); emit('beacons.on'); }
  hintWait();
}
document.querySelectorAll('[data-beacons]').forEach((b) => b.addEventListener('click', () => { firstInteraction('band'); setBeacons(!beaconsOn); }));
document.querySelectorAll('[data-swell]').forEach((sw) => sw.addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b || b.dataset.var === swellVar) return;
  swellVar = b.dataset.var; store.set('nss.swell', swellVar); renderPanel(); requestDraw(); warm(); emit('swell.measure');
}));
// The panel's state and its side are settings (Menu › Settings): applied at
// once, behind the menu, and kept for next time.
function setDocked(d, first) {
  docked = d; store.set('nss.docked', d);
  applyPanels(); renderSettings(); fitKeys();
  if (!first) { easeClamp(); emit('panel.changed'); }
}
function setHand(h, first) {
  hand = h === 'left' ? 'left' : 'right'; store.set('nss.hand', hand);
  document.documentElement.dataset.hand = hand;
  renderSettings(); renderHint();
  if (!first) easeClamp();
}
// The open panel or the docked column, whichever is in use.
function applyPanels() {
  panelEl.toggleAttribute('data-away', sideOn()); columnEl.toggleAttribute('data-away', !sideOn());
  applyInert(); placeTrack(); renderHint();
}
// Only what's showing can be reached: the panel in use, or the menu over it.
function applyInert() {
  panelEl.inert = sideOn() || !!sheetOn; columnEl.inert = !sideOn() || !!sheetOn; cv.inert = !!sheetOn;
}

// ---- Menu: a sheet from the bottom, then Settings or About in its place ---------------------
const scrim = $('#scrim'), sheets = {};
document.querySelectorAll('[data-sheet]').forEach((s) => { sheets[s.dataset.sheet] = s; });
let sheetOn = null, sheetT = 0;
const menuBtn = () => (sideOn() ? columnEl : panelEl).querySelector('[data-menu]');
const focusables = (s) => [...s.querySelectorAll('button, a[href], textarea')].filter((b) => !b.disabled && !b.closest('[hidden]'));
// Shown or not, sliding there or (switching sheets, or with Reduce Motion) not.
function reveal(el, on, slide) {
  if (!slide) el.style.transition = 'none';
  el.toggleAttribute('data-shown', on);
  if (!slide) { void el.offsetHeight; el.style.transition = ''; }
}
function openSheet(name, focus) {
  if (guideOn()) endGuide(false);
  clearTimeout(sheetT);
  const slide = !sheetOn && !reduced.matches, s = sheets[name];
  for (const o of Object.values(sheets)) if (o !== s) { o.hidden = true; o.removeAttribute('data-shown'); }
  scrim.hidden = false; s.hidden = false;
  void s.offsetHeight;                     // rises from below the screen
  reveal(s, true, slide); reveal(scrim, true, slide);
  sheetOn = name; applyInert();
  (focus ? s.querySelector(focus) : focusables(s)[0]).focus({ preventScroll: true });
  hintOpened.add(name); renderHint();
}
function closeSheet() {
  if (!sheetOn) return;
  // Closed on first open without picking: the language it opened in stands.
  if (sheetOn === 'language' && langFirst) keepLang();
  const s = sheets[sheetOn], slide = !reduced.matches;
  sheetOn = null; applyInert();
  reveal(s, false, slide); reveal(scrim, false, slide);
  sheetT = setTimeout(() => { s.hidden = true; scrim.hidden = true; }, slide ? 240 : 0);
  menuBtn().focus({ preventScroll: true });
}
function renderSettings() {
  const on = { panel: docked ? 'side' : 'bottom', hand, tips: hs.tipsOn ? 'on' : 'off' };
  document.querySelectorAll('[data-set]').forEach((sw) => sw.querySelectorAll('button').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.value === on[sw.dataset.set]));
  }));
}
document.querySelectorAll('[data-menu]').forEach((b) => b.addEventListener('click', () => openSheet('menu')));
scrim.addEventListener('click', closeSheet);
document.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', closeSheet));
document.querySelectorAll('[data-go]').forEach((b) => b.addEventListener('click', () => openSheet(b.dataset.go)));
document.querySelectorAll('[data-back]').forEach((b) => b.addEventListener('click', () => {
  openSheet(b.dataset.back || 'menu', `[data-go="${b.closest('[data-sheet]').dataset.sheet}"]`);
}));
// Chart is where we are: back to it.
document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => {
  if (b.getAttribute('aria-current') === 'page') closeSheet();
}));
document.querySelectorAll('[data-set]').forEach((sw) => sw.addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  if (sw.dataset.set === 'panel' && docked !== (b.dataset.value === 'side')) setDocked(b.dataset.value === 'side');
  if (sw.dataset.set === 'hand' && hand !== b.dataset.value) setHand(b.dataset.value);
  if (sw.dataset.set === 'tips' && hs.tipsOn !== (b.dataset.value === 'on')) setTips(b.dataset.value === 'on');
}));
// Language: picked at once, everything in the new one. From Settings the
// sheet stays, to go back from; on first open, picking one is the answer.
const langList = $('[data-langs]');
let langFirst = false;
langList.innerHTML = Object.entries(LANGS).map(([c, L]) => `<li><button type="button" class="nss-menu-item" role="radio" data-lang="${c}" lang="${L.tag}">` +
  `<span class="nss-menu-text"><span class="nss-menu-name">${L.name}</span><span class="nss-menu-sub">${L.places}</span></span>${icon('check', ' nss-icon--sm')}</button></li>`).join('');
function renderLangs() {
  langList.querySelectorAll('[data-lang]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.lang === lang)));
}
function keepLang() {
  store.set('nss.lang', lang);
  if (langFirst) { langFirst = false; setTimeout(() => langMode(false), 300); }   // once it has gone
}
function setLang(c) {
  lang = c;
  applyLang(); renderLangs(); renderPanel(); renderPlay(); renderHint(); buildTicks();
  if (man) setFrame(idx, true);
  statusEls[0].dataset.shown = ''; renderStatus();
  requestDraw();
}
langList.addEventListener('click', (e) => {
  const b = e.target.closest('[data-lang]');
  if (!b) return;
  if (b.dataset.lang !== lang) setLang(b.dataset.lang);
  const first = langFirst;
  keepLang();
  if (first) closeSheet();
});
// First open (or nothing kept): the sheet by itself, no way back to Settings
// but a word on where to find it, and the phone's own language picked.
function langMode(first) {
  const s = sheets.language;
  langFirst = first;
  s.querySelector('[data-back]').hidden = first;
  s.querySelector('[data-lang-lede]').hidden = !first;
  s.querySelector('[data-lang-foot]').hidden = !first;
}
function askLang() { langMode(true); openSheet('language', '[aria-checked="true"]'); }

// Feedback: sent as it is to the Worker that emails it (feedback/), with the
// language, where the app is open and this deploy, and cleared once it's gone.
const fb = $('#feedback'), fbText = $('#fbText'), fbSend = fb.querySelector('[type="submit"]'), fbState = $('#fbState');
let fbSending = false;
const fbReady = () => { fbSend.disabled = fbSending || !fbText.value.trim(); };
fbText.addEventListener('input', () => { fbState.textContent = ''; fbReady(); });
fb.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = fbText.value.trim();
  if (!text || fbSending) return;
  fbSending = true; fbReady(); fbState.textContent = tr('sending');
  try {
    const r = await fetch('/api/feedback', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, website: fb.elements.website.value, lang, surface: document.documentElement.dataset.surface, v: VERSION })
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    fbText.value = ''; fbState.textContent = tr('sent');
  } catch {
    fbState.textContent = tr(navigator.onLine === false ? 'sendOffline' : 'sendFailed');
  }
  fbSending = false; fbReady();
});
// With the keyboard up, the sheet sits on it rather than behind it, and the
// box stays in sight.
if (window.visualViewport) {
  const kb = () => {
    const v = visualViewport, h = Math.max(0, Math.round(innerHeight - v.height - v.offsetTop));
    document.documentElement.style.setProperty('--kb', `${h}px`);
    if (h && document.activeElement === fbText) fbText.scrollIntoView({ block: 'nearest' });
  };
  visualViewport.addEventListener('resize', kb);
  visualViewport.addEventListener('scroll', kb);
}

// Focus stays in the sheet; Escape closes it.
document.addEventListener('keydown', (e) => {
  if (!sheetOn) return;
  if (e.key === 'Escape') { e.preventDefault(); closeSheet(); return; }
  if (e.key !== 'Tab') return;
  const f = focusables(sheets[sheetOn]), i = f.indexOf(document.activeElement);
  if (i < 0 || (e.shiftKey ? i === 0 : i === f.length - 1)) { e.preventDefault(); f[e.shiftKey ? f.length - 1 : 0].focus(); }
});
// A swipe down on the grip pulls the sheet down: far or fast enough, it closes.
document.querySelectorAll('.nss-sheet-grip').forEach((g) => {
  const s = g.closest('[data-sheet]');
  let pull = null;
  g.addEventListener('pointerdown', (e) => {
    g.setPointerCapture(e.pointerId);
    pull = { y: e.clientY, t: performance.now(), dy: 0 };
    s.style.transition = 'none';
  });
  g.addEventListener('pointermove', (e) => {
    if (!pull) return;
    pull.dy = Math.max(0, e.clientY - pull.y);
    s.style.transform = `translateY(${pull.dy}px)`;
  });
  const end = () => {
    if (!pull) return;
    const p = pull, fast = p.dy > 16 && p.dy / (performance.now() - p.t) > 0.5;
    pull = null;
    s.style.transition = ''; s.style.transform = '';
    if (p.dy > 60 || fast) closeSheet();
  };
  g.addEventListener('pointerup', end);
  g.addEventListener('pointercancel', end);
});

// ---- Time readout and status -------------------------------------------------------------
// The formatters are the language's (applyLang). Short weekdays without the
// full stop some languages give them (man., lun.).
const weekday = (t) => fWeek.format(t).replace(/\.$/, '');
const dayName = (t) => `${weekday(t)} ${new Date(t).getDate()}`;
const setText = (sel, text) => document.querySelectorAll(sel).forEach((el) => { el.textContent = text; });
function renderReadout() {
  if (!man) return;
  const t = validAt(man, idx), label = tr('forecastAt', { when: `${fLong.format(t)} ${fHour.format(t)}` });
  setText('[data-day]', dayName(t).toLocaleUpperCase(LANGS[lang].tag));
  setText('[data-lead]', `+${man.steps[idx]}H`);
  setText('[data-time]', fHour.format(t));
  $('#readout').setAttribute('aria-label', label);
  $('#colTime').setAttribute('aria-label', label);
}
const zHour = (t) => String(new Date(t).getUTCHours()).padStart(2, '0');
function runName(m) { return tr('run', { day: weekday(m.run), hh: zHour(m.run) }); }
const statusEls = [$('#rStatus'), $('#colStatus')], madeEl = $('#rMade');
// When the run on show was published: its time, and its day too if not today.
function madeName(m) {
  const t = m.made || m.run, day = new Date(t).toDateString() === new Date().toDateString() ? '' : `${weekday(t)} `;
  return tr('made', { when: day + fHour.format(t) });
}
function renderStatus() {
  let text = '', kind = '';
  if (!man) [text, kind] = offline ? [tr('offline'), 'offline'] : [tr('loading'), 'loading'];
  else if (!frames[idx] && !offline) [text, kind] = [tr('loading'), 'loading'];
  else if (offline) [text, kind] = [tr('offlineRun', { run: runName(man) }), 'offline'];
  else if (Date.now() - man.run > 12 * H) [text, kind] = [tr('old', { n: Math.round((Date.now() - man.run) / H) }), 'old'];
  else if (updatedNote) [text, kind] = [tr('updated', { hh: zHour(man.run) }), 'updated'];
  // A quiet "Updated 14:32" while there's nothing else to say.
  const made = man && !kind ? madeName(man) : '';
  madeEl.textContent = made; madeEl.hidden = !made;
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
const tl = { raw: 0, target: 0, anim: 0, v: 0, moving: false };
const TL = [...document.querySelectorAll('[data-axis]')].map((el) => ({
  el, axis: el.dataset.axis, track: el.querySelector('[data-track]'), progress: el.querySelector('[data-progress]'), ticks: []
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
      const name = T.axis === 'x' ? dayName(d.getTime()) : weekday(d);
      html.push(`<span class="nss-tick nss-tick--day${past ? ' nss-tick--past' : ''}" style="${at}:${p.toFixed(1)}px"></span><span class="nss-day${past}" style="${at}:${(p + label).toFixed(1)}px">${name}</span>`);
    }
    const np = fracIndex(now);
    if (np >= -0.5 && np <= n - 0.5) html.push(`<span class="nss-tick nss-tick--now" style="${at}:${(np * TICK).toFixed(1)}px"></span>`);
    html.push(`<span class="nss-end" style="${at}:${(n - 1) * TICK + 4}px"></span>`);
    T.track.innerHTML = html.join('');
    T.ticks = [...T.track.querySelectorAll('.nss-tick:not(.nss-tick--day):not(.nss-tick--now)')];
    T.el.setAttribute('aria-valuemax', String(n - 1));
  }
  renderRows();
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
  placeRows();
}
// Build the band's frames either side of the needle while nothing else is
// happening, so scanning finds them ready. Not while the timeline moves: each
// takes a phone tens of ms, which the scale would stall for.
let warmT = 0;
function warm() {
  clearTimeout(warmT);
  warmT = setTimeout(function next() {
    if (!man || tl.moving) return;
    for (let d = 1; d <= 16; d++) {
      for (const i of [idx + d, idx - d]) {
        if (i < 0 || i >= man.steps.length || !frames[i] || geomReady(i)) continue;
        buildGeom(i); warmT = setTimeout(next, 0); return;
      }
    }
  }, 60);
}
function setFrame(i, force) {
  if (!man) return;
  i = Math.max(0, Math.min(maxPos(), i));
  if (i === idx && !force) return;
  idx = i;
  const t = validAt(man, i);
  // The progress line: where the needle is in the whole run.
  const pc = `${maxPos() ? (100 * i / maxPos()).toFixed(2) : 0}%`;
  for (const T of TL) {
    T.el.setAttribute('aria-valuenow', String(i));
    T.el.setAttribute('aria-valuetext', `${fLong.format(t)}, ${fHour.format(t)}` + (T.axis === 'x' ? beaconSaid(i) : ''));
    T.progress.style.setProperty('--progress', pc);
  }
  renderReadout(); renderStatus(); renderBeaconNumbers(); requestDraw(); pump(); warm();
}
function moveTo(raw) {
  tl.raw = raw; placeTrack();
  setFrame(Math.round(Math.max(0, Math.min(maxPos(), raw))));
}
function animateTo(target, dur = 220) {
  cancelAnimationFrame(tl.anim);
  tl.moving = true;
  const from = tl.raw, start = performance.now();
  if (reduced.matches) dur = 0;
  const step = (t) => {
    const q = dur ? Math.min(1, (t - start) / dur) : 1, e = 1 - Math.pow(1 - q, 3);
    moveTo(from + (target - from) * e);
    if (q < 1) { tl.anim = requestAnimationFrame(step); return; }
    tl.moving = false; requestDraw(); warm(); hintWait();
  };
  tl.anim = requestAnimationFrame(step);
}
const settle = () => animateTo(Math.round(Math.max(0, Math.min(maxPos(), tl.raw))));
let drag = null, tlTap = 0;
// ?debug=1: what the last drag of the timeline was like (see the readout).
const tlDbg = Q.has('debug') ? { last: null, cur: null } : null;
// The drag is timed by when the page gets each move and the lift, on the
// page's own clock, not by the times the events carry: iOS can stamp the lift
// on a different footing from the moves, which reads as a finger that stopped
// before it lifted, and no flick.
// How fast the scale was moving as the finger left it, in frames per ms: from
// the last moments of the drag, and none if the finger stopped before lifting:
// no move for 120 ms, or for twice the gap between the last two moves when a
// busy page spaced them out further than that.
function releaseSpeed(d, now) {
  const s = d.samples, [t1, r1] = s[s.length - 1], [t0, r0] = s[0];
  const gap = s.length > 1 ? t1 - s[s.length - 2][0] : 0;
  if (now - t1 > Math.max(120, 2 * gap) || t1 - t0 < 8) return 0;
  return (r1 - r0) / (t1 - t0);
}
for (const T of TL) {
  const along = (e) => (T.axis === 'x' ? e.clientX : e.clientY);
  T.el.addEventListener('pointerdown', (e) => {
    if (!man) return;
    stopPlay();
    T.el.setPointerCapture(e.pointerId);
    cancelAnimationFrame(tl.anim);
    tl.moving = true;
    const now = performance.now();
    drag = { c: along(e), c0: along(e), t0: now, samples: [[now, tl.raw]], stamp: e.timeStamp };
    if (tlDbg) tlDbg.cur = { moves: 0, merged: 0, touches: 0, end: '', slowest: 0, builds: 0, raw: e.timeStamp };
  });
  T.el.addEventListener('pointermove', (e) => {
    if (!drag) return;
    // The scale follows the finger: dragging left, or up, moves on in time.
    const all = e.getCoalescedEvents ? e.getCoalescedEvents() : [];
    if (tlDbg && tlDbg.cur) { tlDbg.cur.moves++; tlDbg.cur.merged += all.length || 1; }
    const now = performance.now(), dc = along(e) - drag.c;
    drag.c = along(e); drag.stamp = e.timeStamp;
    moveTo(tl.raw - dc / TICK);
    if (Math.abs(drag.c - drag.c0) > 6) firstInteraction('rail');
    drag.samples.push([now, tl.raw]);
    while (drag.samples.length > 2 && now - drag.samples[0][0] > 120) drag.samples.shift();
  });
  const end = (e) => {
    if (!drag) return;
    const now = performance.now(), d = drag;
    drag = null;
    if (Math.abs(d.c - d.c0) < 6 && now - d.t0 < 300) {
      if (now - tlTap < 320) { tlTap = 0; firstInteraction('rail'); emit('timeline.reset'); animateTo(nearestIndex(man, Date.now()), 360); return; }
      tlTap = now; settle(); return;
    }
    emit('timeline.drag');
    const v = releaseSpeed(d, now);
    if (tlDbg && tlDbg.cur) {
      const c = tlDbg.cur, s = d.samples;
      Object.assign(c, { end: e.type, gap: now - s[s.length - 1][0], stampGap: e.timeStamp - d.stamp, span: s[s.length - 1][0] - s[0][0], v, flick: !(Math.abs(v) < 0.015 || tl.raw < 0 || tl.raw > maxPos()) });
      tlDbg.last = c;
    }
    // With Reduce Motion too: like a list's own scrolling on iOS, the glide is
    // the finger's doing, not motion put on the page.
    if (Math.abs(v) < 0.015 || tl.raw < 0 || tl.raw > maxPos()) { settle(); return; }
    // A flick rolls on and slows to a stop, passing frames on the way: a soft
    // one a few hours, a hard one (faster swipes count for more) the whole run.
    let vel = v * (1 + 6 * Math.abs(v)), last = now;
    const step = (t) => {
      const dt = Math.max(0, Math.min(250, t - last)); last = t;
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
    e.preventDefault(); firstInteraction('rail'); emit('timeline.drag'); stopPlay();
    to = Math.max(0, Math.min(n, to));
    tl.raw = to; placeTrack(); setFrame(to);
  });
}

// ---- Play: on through the run from the needle --------------------------------------------
// About four frames a second, the scale sliding under the needle as if
// dragged (frame by frame with Reduce Motion), waiting on a frame still to
// load, and stopping on the last. Touching the timeline pauses it, for good;
// nothing else that doesn't move time (the map, the bands) does.
const PLAY_RATE = 4 / 1000;   // frames a ms
const play = { on: false, pos: 0, last: 0 };
const playBtns = [...document.querySelectorAll('[data-play]')];
function renderPlay() {
  for (const b of playBtns) {
    b.setAttribute('aria-pressed', String(play.on));
    b.setAttribute('aria-label', tr(play.on ? 'pause' : 'play'));
    b.innerHTML = icon(play.on ? 'pause' : 'play');
  }
}
renderPlay();
function playStep(t) {
  const dt = Math.max(0, Math.min(250, t - play.last)), m = maxPos(), next = Math.floor(play.pos) + 1;
  play.last = t;
  if (next > m || frames[next]) play.pos = Math.min(m, play.pos + dt * PLAY_RATE);
  moveTo(reduced.matches ? Math.floor(play.pos) : play.pos);
  if (play.pos >= m) { stopPlay(); settle(); return; }
  tl.anim = requestAnimationFrame(playStep);
}
function startPlay() {
  if (!man || idx >= maxPos()) return;
  cancelAnimationFrame(tl.anim);
  play.on = true; play.pos = idx; play.last = performance.now();
  tl.moving = true;
  renderPlay();
  tl.anim = requestAnimationFrame(playStep);
}
function stopPlay() {
  if (!play.on) return;
  play.on = false;
  cancelAnimationFrame(tl.anim);
  tl.moving = false;
  renderPlay(); requestDraw(); warm(); hintWait();
}
for (const b of playBtns) b.addEventListener('click', () => {
  if (play.on) { stopPlay(); settle(); return; }
  firstInteraction('play'); startPlay();
});

// ---- Beacon: a forecast point dropped on a sea grid point -----------------------------------
// The sea grid points (NOAA's cells: grid.js) carry small crosses, thinned
// out as the map zooms out and filling in as it zooms in. Tap one and a
// lifeboat beacon drops there, pings three times, and the map glides (and
// zooms in, if need be) to put it a quarter of the way down, straight above
// the needle; the open panel becomes its sheet, with the cell's
// modelled wind and swell drawn on the timeline's own track, so one needle
// reads everything. One beacon at a time; the link (?at=lat,lon) opens one.
const CROSS_GAP = 16, CROSS_HIT = 22, BEACON_AT = 0.25, BEACON_GAP = 24;
// Not settled yet: a beacon panned off its place loses its tie and notch
// until the next drop (false: they come back when it's back).
const TIE_STAYS_OUT = true;
let beacon = null, glideAnim = 0, crossPts = [], rowArrows = [];
const crossTiles = new Map();
const markEl = $('[data-beacon-mark]'), tieEl = $('[data-tie]'), rowsTrack = $('[data-rows-track]');
const copyBtn = $('[data-beacon-copy]'), saidEl = $('[data-beacon-said]'), grip = $('[data-beacon-grip]');
const vals = Object.fromEntries([...document.querySelectorAll('[data-val]')].map((el) => [el.dataset.val, el]));
const marks = Object.fromEntries([...document.querySelectorAll('[data-mark]')].map((el) => [el.dataset.mark, el]));
// The rows: three of 66 px (a 28 px band of numbers over 38 px of plot)
// split by hairlines, pressure at 0, wind at 67, swell at 134. Wind's plot
// is its arrows over 20 px of speed.
const ROWS = { h: 200, plotH: 38, plot: { pressure: 28, wind: 95, swell: 162 }, arrowY: 104, speedTop: 113, speedH: 20,
  pMin: 990, pMax: 1020, windMax: 35, swellMax: 3 };

// The km between neighbouring grid points down (a row) and across (a
// column) at a latitude.
const cellKm = (lat) => ({ row: 111.2 / grid.lattice, col: 111.2 / grid.lattice * Math.cos(lat * Math.PI / 180) });
// Which grid points get a cross, so none sit closer than CROSS_GAP px: every
// one when zoomed in that far, else every 2nd, 4th, 8th... row and column,
// counted on NOAA's own lattice, so zooming in only ever adds crosses
// between the ones already there.
function crossStride() {
  const km = cellKm(grid.kmToLonLat(view.x, view.y)[1]), st = (d) => 2 ** Math.max(0, Math.ceil(Math.log2(CROSS_GAP / (d * view.k))));
  return { row: st(km.row), col: st(km.col) };
}
// The crosses in sight: from the manifest's sea mask, at any zoom; from a
// manifest without one, from the tiles under the screen (each fetched once),
// zoomed in to where every point shows. With a beacon's wind on, each point
// carries the wind's arrow there instead (a calm point keeps its cross),
// still the place to tap.
function drawCrosses(sx, sy, pb, L, fi) {
  crossPts = [];
  // With Beacons on only, and only from beacons' minimum zoom in.
  if (!grid || !grid.seaPoints || !beaconsOn || !beaconsReach()) return;
  const st = crossStride();
  const path = new Path2D(), arrows = new Path2D(), d = L.points && fi >= 0 && frames[fi];
  const P = man.grids.p, sq = man.square, ws = man.scale.wind || 2;
  const add = (c) => {
    // In Saltburn's swell window only (worked out once a point).
    if (c.win === undefined && swellWin !== null) c.win = inWindow(c.lat, c.lon);
    if (!c.win) return;
    const px = sx(c.x), py = sy(c.y);
    if (px < -7 || px > W + 7 || py < -7 || py > Hs + 7 || (px > pb.x0 && px < pb.x1 && py > pb.y)) return;
    if (d) {
      const gj = (c.x - sq.x0) / (sq.x1 - sq.x0) * (P - 1), gi = (sq.y0 - c.y) / (sq.y0 - sq.y1) * (P - 1);
      const u = bilinear(d.u, P, gj, gi) / ws, v = bilinear(d.v, P, gj, gi) / ws, sp = Math.hypot(u, v);
      if (sp >= 0.3) { crossPts.push({ c, px, py, arrow: true }); arrowAt(arrows, px, py, u / sp, -v / sp); return; }
    }
    crossPts.push({ c, px, py });
    path.moveTo(px - 4, py); path.lineTo(px + 4, py); path.moveTo(px, py - 4); path.lineTo(px, py + 4);
  };
  const pts = grid.seaPoints();
  if (pts) {
    for (const c of pts) if (!(c.row % st.row) && !(c.col % st.col)) add(c);
  } else {
    let s = 90, n = -90, w = 180, e = -180;
    for (const fx of [-0.5, 0, 0.5]) for (const fy of [-0.5, 0, 0.5]) {
      const [lon, lat] = grid.kmToLonLat(view.x + fx * W / view.k, view.y + fy * Hs / view.k);
      s = Math.min(s, lat); n = Math.max(n, lat); w = Math.min(w, lon); e = Math.max(e, lon);
    }
    for (const name of grid.tilesIn(s - 0.5, n + 0.5, w - 0.5, e + 0.5)) {
      if (!crossTiles.has(name)) {
        crossTiles.set(name, null);
        grid.seaCells(name).then((cells) => {
          crossTiles.set(name, cells.map((c) => { const [x, y] = grid.lonLatToKm(c.lon, c.lat); return { ...c, x, y }; }));
          requestDraw();
        }).catch(() => setTimeout(() => crossTiles.delete(name), 30e3));
        continue;
      }
      for (const c of crossTiles.get(name) || []) add(c);
    }
  }
  // Dark over a key's colours, white at 50% over the plain sea.
  ctx.lineWidth = 1.3; ctx.lineCap = 'butt'; ctx.setLineDash([]);
  ctx.strokeStyle = L.swell || L.field ? C.ink : 'rgba(255,255,255,0.5)';
  ctx.stroke(path);
  ctx.lineWidth = 1.6; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = C.arrow;
  ctx.stroke(arrows);
}
// Beacons' minimum zoom at a latitude: BEACONS_OUT times further out than
// where every grid point shows 16 px apart east to west, the points thinned
// there (crossStride) and filling in as the map zooms in.
const BEACONS_OUT = 2.5;
const beaconsMinK = (lat) => CROSS_GAP / cellKm(lat).col / BEACONS_OUT;
const beaconsReach = () => view.k >= beaconsMinK(grid.kmToLonLat(view.x, view.y)[1]) * 0.999;
// Zoomed out past it with no beacon open (and not on the way in): Beacons
// goes off, and the band comes back.
let beaconsGlide = false, beaconsOffT = 0;
const beaconsBtns = [...document.querySelectorAll('[data-beacons]')];
let beaconsUsable = null;
function checkBeaconsReach() {
  const usable = !!grid && beaconsReach();
  if (usable !== beaconsUsable) { beaconsUsable = usable; for (const b of beaconsBtns) b.disabled = !usable; }
  if (!beaconsOn || beacon || beaconsGlide || !grid || beaconsOffT || beaconsReach()) return;
  beaconsOffT = setTimeout(() => { beaconsOffT = 0; if (beaconsOn && !beacon && !beaconsGlide && !beaconsReach()) setBeacons(false); });
}
// The cross for the first-use tip ("Tap a cross") to point at, pulsing: the
// one nearest the middle of the visible chart, kept while the tip shows.
let crossSpot = null;
const crossSpotEl = $('[data-hint-target="cross"]');
function placeCrossSpot() {
  const tipOn = !!hintOn && hintOn.target === 'cross';
  let p = tipOn && crossSpot && crossPts.find((q) => q.c.id === crossSpot.c.id);
  if (!p && !tipOn && crossPts.length) {
    const v = vis(), cx = v.x + v.w / 2, cy = (sideOn() ? Hs : v.h) / 2;
    p = crossPts.reduce((a, q) => (Math.hypot(q.px - cx, q.py - cy) < Math.hypot(a.px - cx, a.py - cy) ? q : a));
  }
  crossSpot = p || null;
  if (p) crossSpotEl.style.transform = `translate(${p.px.toFixed(1)}px, ${p.py.toFixed(1)}px)`;
  if (tipOn) renderHint();
}
// A tap: the nearest cross within reach, or nothing.
onTap = (cx, cy) => {
  let best = null, bd = CROSS_HIT;
  for (const p of crossPts) { const d = Math.hypot(p.px - cx, p.py - cy); if (d <= bd) { bd = d; best = p.c; } }
  if (best) dropBeacon(best);
};

// Where the beacon sits once recentred: across the middle of the screen, a
// quarter of the way down (and always clear above the sheet).
const beaconY = () => Math.min(Hs * BEACON_AT, Hs - panelH() - 40);
function dropBeacon(c, layers) {
  const opening = !beacon;
  beacon = { id: c.id, lat: c.lat, lon: c.lon, x: c.x, y: c.y, s: null, w: null, tieOk: false, layers: layers || layersFor(c.id) };
  emit('beacon.drop');
  if (opening) {
    if (hintOn) { hintOn = null; hintCard = false; clearTimeout(hintGoT); renderHint(); }
    panelEl.setAttribute('data-beacon', '');
    const T = TL.find((t) => t.axis === 'x');
    T.el.dataset.tLabel = 'beaconTimeline'; T.el.setAttribute('aria-label', tr('beaconTimeline'));
    applyPanels();
  }
  document.documentElement.removeAttribute('data-tied');
  markEl.hidden = tieEl.hidden = false;
  markEl.removeAttribute('data-ping'); void markEl.offsetWidth; markEl.setAttribute('data-ping', '');
  loadBeacon(); renderLayers(); warm();
  setFrame(idx, true);
  recentre();
}
// The beacon's forecast, from its cell's tile (again for a new run).
function loadBeacon() {
  const b = beacon;
  b.s = b.w = null; renderRows();
  if (!grid) return;
  grid.series(b.id).then((s) => {
    if (beacon !== b || !s) return;
    b.s = s; b.w = beaconWind(s);
    renderRows(); setFrame(idx, true);
  }).catch(() => {});
}
// The wind at the beacon: its own cell's GFS for now. A finer model near the
// coast would resolve its own cell from the beacon's lat/lon here.
function beaconWind(s) {
  return {
    speed: Float32Array.from(s.u, (u, i) => Math.hypot(u, s.v[i]) * MPH),
    from: Float32Array.from(s.u, (u, i) => (Math.atan2(-u, -s.v[i]) * 180 / Math.PI + 360) % 360),
    u: s.u, v: s.v
  };
}
function closeBeacon() {
  if (!beacon) return;
  beacon = null;
  cancelAnimationFrame(glideAnim);
  markEl.hidden = tieEl.hidden = true; markEl.removeAttribute('data-ping');
  document.documentElement.removeAttribute('data-tied');
  panelEl.removeAttribute('data-beacon');
  const T = TL.find((t) => t.axis === 'x');
  T.el.dataset.tLabel = 'timeline'; T.el.setAttribute('aria-label', tr('timeline'));
  rowsTrack.innerHTML = ''; rowArrows = [];
  applyPanels(); setFrame(idx, true);
  if (Q.has('at')) {
    const u = new URL(location.href);
    u.searchParams.delete('at'); u.searchParams.delete('layers');
    try { history.replaceState(history.state, '', u); } catch {}
  }
  easeClamp(); menuBtn().focus({ preventScroll: true }); hintWait();
}
// The marker over its grid point, and the tie and notch while it's in its place.
function placeBeacon() {
  if (!beacon) return;
  const px = W / 2 + (beacon.x - view.x) * view.k, py = Hs / 2 - (beacon.y - view.y) * view.k, top = Hs - panelH();
  markEl.style.transform = `translate(${px.toFixed(1)}px, ${py.toFixed(1)}px)`;
  tieEl.style.transform = `translate(${(px - 0.75).toFixed(1)}px, ${(py + 10).toFixed(1)}px)`;
  tieEl.style.height = `${Math.max(0, top - py - 10).toFixed(1)}px`;
  const at = Math.abs(px - W / 2) <= 1.5 && Math.abs(py - beaconY()) <= 1.5;
  if (!at && TIE_STAYS_OUT) beacon.tieOk = false;
  document.documentElement.toggleAttribute('data-tied', beacon.tieOk && at);
}
// cubic-bezier(0.2, 0.7, 0.2, 1), the glide's easing.
function glideEase(q) {
  const B = (a, b, t) => 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3;
  let lo = 0, hi = 1, t = q;
  for (let i = 0; i < 24; i++) { t = (lo + hi) / 2; if (B(0.2, 0.2, t) < q) lo = t; else hi = t; }
  return B(0.7, 1, t);
}
// The one time the map moves itself: on a drop, a single glide (a jump with
// Reduce Motion) of the same view the fingers move, zooming in if need be
// until its neighbours' crosses sit BEACON_GAP px apart; then the tie. The
// beacon runs straight to its place as the zoom eases in.
function recentre() {
  cancelAnimationFrame(glideAnim);
  const b = beacon, from = { ...view }, k1 = Math.min(kMax(), Math.max(view.k, BEACON_GAP / cellKm(b.lat).col));
  view = { x: b.x, y: b.y + (beaconY() - Hs / 2) / k1, k: k1 };
  clampView();
  const to = { ...view }, at = (v) => [W / 2 + (b.x - v.x) * v.k, Hs / 2 - (b.y - v.y) * v.k];
  const [x0, y0] = at(from), [x1, y1] = at(to);
  view = from;
  const done = () => { view = to; saveView(); if (beacon === b) b.tieOk = true; requestDraw(); };
  if (reduced.matches) { done(); return; }
  const start = performance.now();
  const step = (t) => {
    const q = Math.min(1, (t - start) / 600), e = glideEase(q), k = from.k * Math.pow(to.k / from.k, e);
    const px = x0 + (x1 - x0) * e, py = y0 + (y1 - y0) * e;
    view = { x: b.x - (px - W / 2) / k, y: b.y + (py - Hs / 2) / k, k };
    requestDraw();
    if (q < 1) glideAnim = requestAnimationFrame(step); else done();
  };
  glideAnim = requestAnimationFrame(step);
}

// Show me, zoomed out: one glide in, about the middle of the visible chart,
// to beacons' minimum zoom (a jump with Reduce Motion); already there,
// nothing moves.
function zoomToBeacons() {
  if (!grid) return;
  const v = vis(), cx = v.x + v.w / 2, cy = (sideOn() ? Hs : v.h) / 2;
  const lat = grid.kmToLonLat(view.x + (cx - W / 2) / view.k, view.y - (cy - Hs / 2) / view.k)[1];
  const k1 = Math.min(kMax(), beaconsMinK(lat) * 1.01), k0 = view.k;
  if (k0 >= k1) return;
  cancelAnimationFrame(glideAnim);
  if (reduced.matches) { zoomAbout(cx, cy, k1 / k0); clampView(); requestDraw(); saveView(); return; }
  const start = performance.now();
  let done = 1;
  beaconsGlide = true;
  const step = (t) => {
    const q = Math.min(1, (t - start) / 600), f = Math.pow(k1 / k0, glideEase(q));
    zoomAbout(cx, cy, f / done); done = f;
    clampView(); requestDraw();
    if (q < 1) glideAnim = requestAnimationFrame(step); else { beaconsGlide = false; saveView(); hintWait(); }
  };
  glideAnim = requestAnimationFrame(step);
}

// ---- The beacon's rows: pressure, wind and swell on the timeline's track ----
const arrowPath = (x, y, dx, dy, half, head) => {
  const hx = x + dx * half, hy = y + dy * half, c = Math.cos(Math.PI / 6), s = Math.sin(Math.PI / 6);
  return `M${(x - dx * half).toFixed(1)} ${(y - dy * half).toFixed(1)}L${hx.toFixed(1)} ${hy.toFixed(1)}` +
    `M${(hx - head * (dx * c - dy * s)).toFixed(1)} ${(hy - head * (dy * c + dx * s)).toFixed(1)}L${hx.toFixed(1)} ${hy.toFixed(1)}` +
    `L${(hx - head * (dx * c + dy * s)).toFixed(1)} ${(hy - head * (dy * c - dx * s)).toFixed(1)}`;
};
function renderRows() {
  const s = beacon && beacon.s;
  rowArrows = [];
  if (!s || !man || s.run !== man.run) { rowsTrack.innerHTML = ''; return; }
  const n = Math.min(man.steps.length, s.hs.length), w = beacon.w, now = Date.now(), R = ROWS, out = [];
  const X = (i) => i * TICK, past = (i) => validAt(man, i) < now;
  // A value up a plot, clamped to its scale.
  const up = (v, top, h, lo, hi) => top + h - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * h;
  const py = (i) => up(s.p[i], R.plot.pressure, R.plotH, R.pMin, R.pMax);
  const wy = (i) => up(w.speed[i], R.speedTop, R.speedH, 0, R.windMax);
  const hy = (i) => up(s.hs[i], R.plot.swell, R.plotH, 0, R.swellMax);
  // Midnights through all three rows, in line with the scale's day ticks.
  const first = new Date(validAt(man, 0)); first.setHours(24, 0, 0, 0);
  for (let d = new Date(first); d.getTime() <= validAt(man, n - 1); d.setDate(d.getDate() + 1)) {
    const x = (fracIndex(d.getTime()) * TICK).toFixed(1);
    out.push(`<line x1="${x}" y1="0" x2="${x}" y2="${R.h}" stroke="${C.ink}" stroke-opacity="0.12"/>`);
  }
  // A fill frame by frame, its top meeting the next frame's halfway.
  const fill = (y, base, col) => {
    let o = '';
    for (let i = 0; i < n; i++) {
      const y0 = y(i);
      if (Number.isNaN(y0)) continue;
      const yl = i && !Number.isNaN(y(i - 1)) ? (y(i - 1) + y0) / 2 : y0, yr = i < n - 1 && !Number.isNaN(y(i + 1)) ? (y(i + 1) + y0) / 2 : y0;
      o += `<path d="M${X(i) - 4} ${base}V${yl.toFixed(1)}L${X(i)} ${y0.toFixed(1)}L${X(i) + 4} ${yr.toFixed(1)}V${base}Z" fill="${col(i)}"/>`;
    }
    return o;
  };
  const line = (y) => {
    let d = '', pen = false;
    for (let i = 0; i < n; i++) {
      const v = y(i);
      if (Number.isNaN(v)) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${X(i)} ${v.toFixed(1)}`; pen = true;
    }
    return d;
  };
  // The past, washed out as the scale's past ticks are.
  const np = Math.min(X(n - 1) + 4, fracIndex(now) * TICK);
  const wash = (top, h) => (np > -4 ? `<rect x="-4" y="${top}" width="${(np + 4).toFixed(1)}" height="${h}" fill="${C.raised}" fill-opacity="0.6"/>` : '');
  const row = (name, body) => `<g data-row="${name}">${body}</g>`;
  // Pressure: a line over a faint fill, 990 to 1020 hPa.
  const pBase = R.plot.pressure + R.plotH;
  out.push(row('pressure', fill(py, pBase, () => C.ink).replace(/fill="[^"]+"/g, `fill="${C.ink}" fill-opacity="0.07"`) +
    `<path d="${line(py)}" fill="none" stroke="${C.ink}" stroke-width="1.5" stroke-linejoin="round"/>` + wash(R.plot.pressure, R.plotH)));
  // Wind: arrows downwind every third frame, then speed up the row in the
  // key's stepped colours with a line on top.
  let wind = fill(wy, R.speedTop + R.speedH, (i) => binColour(KEYS.wind, w.speed[i])) +
    `<path d="${line(wy)}" fill="none" stroke="${C.control}" stroke-width="1.2" stroke-linejoin="round"/>` + wash(R.speedTop, R.speedH);
  for (let i = 0; i < n; i += 3) {
    const sp = Math.hypot(w.u[i], w.v[i]);
    if (!(sp > 0.2)) continue;
    wind += `<path data-x="${X(i)}" data-h="7" d="${arrowPath(X(i), R.arrowY, w.u[i] / sp, -w.v[i] / sp, 7, 4.5)}" fill="none" stroke="${C.ink}"` +
      ` stroke-width="1.7" stroke-linecap="square"${past(i) ? ' opacity="0.35"' : ''}/>`;
  }
  out.push(row('wind', wind));
  // Swell: height up the row, the fill in the period's stepped colours, the
  // line in the height's (stepped too) over a darker one, and the swell's way
  // every 6 hours.
  const sBase = R.plot.swell + R.plotH;
  let swell = fill(hy, sBase, (i) => binColour(KEYS.period, s.tp[i])) +
    `<path d="${line(hy)}" fill="none" stroke="${C.ink}" stroke-opacity="0.5" stroke-width="4.5" stroke-linejoin="round" stroke-linecap="round"/>`;
  for (let i = 0; i < n - 1; i++) {
    if (Number.isNaN(s.hs[i]) || Number.isNaN(s.hs[i + 1])) continue;
    swell += `<line x1="${X(i)}" y1="${hy(i).toFixed(1)}" x2="${X(i + 1)}" y2="${hy(i + 1).toFixed(1)}" stroke="${binColour(KEYS.height, (s.hs[i] + s.hs[i + 1]) / 2)}" stroke-width="3" stroke-linecap="round"/>`;
  }
  for (let i = 0; i < n; i++) {
    if (man.steps[i] % 6 || Number.isNaN(s.dp[i]) || hy(i) > sBase - 14) continue;
    const g = (s.dp[i] + 180) * Math.PI / 180;
    swell += `<path data-x="${X(i)}" data-h="4" d="${arrowPath(X(i), sBase - 6, Math.sin(g), -Math.cos(g), 4, 3)}" fill="none" stroke="#fff"` +
      ` stroke-opacity="0.9" stroke-width="1.3" stroke-linecap="square"/>`;
  }
  out.push(row('swell', swell + wash(R.plot.swell, R.plotH)));
  rowsTrack.innerHTML = `<svg width="${X(n)}" height="${R.h}" aria-hidden="true"><filter id="nss-mono"><feColorMatrix type="saturate" values="0"/></filter>${out.join('')}</svg>`;
  rowArrows = [...rowsTrack.querySelectorAll('[data-x]')].map((el) => ({ el, x: +el.dataset.x, half: +el.dataset.h, off: false }));
  renderLayers();
  placeRows();
}
// With the scale: the same offset, the arrows by the needle put away, and
// the needle's marks where it crosses each curve.
function placeRows() {
  if (!beacon) return;
  const pos = shownPos();
  rowsTrack.style.transform = `translateX(${(-pos * TICK).toFixed(2)}px)`;
  for (const a of rowArrows) {
    const off = Math.abs(a.x - pos * TICK) < 10 + a.half;
    if (off !== a.off) { a.off = off; a.el.style.visibility = off ? 'hidden' : ''; }
  }
  const s = beacon.s, R = ROWS;
  if (!s || s.run !== man.run) { for (const m of Object.values(marks)) m.hidden = true; return; }
  const n = Math.min(man.steps.length, s.hs.length), p = Math.max(0, Math.min(n - 1, pos)), i = Math.min(n - 2, Math.floor(p)), f = p - i;
  const at = (a) => a[i] + (a[i + 1] - a[i]) * f;
  const mark = (el, v, top, h, lo, hi) => {
    el.hidden = Number.isNaN(v);
    if (!el.hidden) el.style.top = `${(top + h - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * h - 3).toFixed(1)}px`;
  };
  mark(marks.pressure, at(s.p), R.plot.pressure, R.plotH, R.pMin, R.pMax);
  mark(marks.wind, at(beacon.w.speed), R.speedTop, R.speedH, 0, R.windMax);
  mark(marks.swell, at(s.hs), R.plot.swell, R.plotH, 0, R.swellMax);
}
// The readings at a frame, rounded as shown: hPa, s and mph whole, m to 0.1;
// and pressure's change over the 6 hours before (none at the run's start).
const compass = (deg, long) => (long ? tr('compassLong').split(',') : tr('compass').split(' '))[Math.round(deg / 22.5) % 16];
function reading(i) {
  const s = beacon && beacon.s;
  if (!s || s.run !== man.run || i >= s.hs.length) return null;
  const w = beacon.w, ok = (x) => !Number.isNaN(x), j = man.steps.indexOf(man.steps[i] - 6);
  const trend = j >= 0 && ok(s.p[i]) && ok(s.p[j]) ? s.p[i] - s.p[j] : null;
  return {
    p: ok(s.p[i]) ? Math.round(s.p[i]) : null, trend,
    speed: ok(w.speed[i]) ? Math.round(w.speed[i]) : null, wfrom: w.from[i],
    hs: ok(s.hs[i]) ? s.hs[i].toFixed(1) : null, tp: ok(s.tp[i]) ? Math.round(s.tp[i]) : null, tpRaw: s.tp[i], sfrom: s.dp[i]
  };
}
const dirIcon = (from) => `<svg viewBox="0 0 12 12" aria-hidden="true" style="transform: rotate(${Math.round(from + 180)}deg)">` +
  '<path d="M6 10.5 V1.8 M2.8 5 L6 1.8 L9.2 5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="square"></path></svg>';
const trendIcon = (fall) => `<svg class="nss-trend" viewBox="0 0 12 12" aria-hidden="true"><path d="${fall ? 'M1.5 3 H10.5 L6 10 Z' : 'M1.5 9 H10.5 L6 2 Z'}" fill="currentColor"></path></svg>`;
function renderBeaconNumbers() {
  if (!beacon) return;
  const r = reading(idx), put = (k, html) => { if (vals[k].innerHTML !== html) vals[k].innerHTML = html; };
  const dir = (deg) => (r && !Number.isNaN(deg) ? dirIcon(deg) + compass(deg) : '');
  put('p', !r ? '' : r.p == null ? '–' : `${r.p}<small> hPa</small>`);
  put('ptrend', !r || r.trend == null ? '' : `${Math.abs(r.trend) >= 0.05 ? trendIcon(r.trend < 0) : ''}${Math.abs(r.trend).toFixed(1)}<small> /6H</small>`);
  put('wind', !r ? '' : r.speed == null ? '–' : `${r.speed}<small> mph</small>`);
  put('wdir', r && r.speed ? dir(r.wfrom) : '');
  put('hs', !r ? '' : r.hs == null ? '–' : `${r.hs}<small> m</small>`);
  put('tp', !r || r.tp == null ? '' : `<i style="background: ${binColour(KEYS.period, r.tpRaw)}"></i>${r.tp}<small> s</small>`);
  put('sdir', r ? dir(r.sfrom) : '');
}
// The readings for a screen reader, after the day and time.
function beaconSaid(i) {
  const r = beacon && reading(i);
  if (!r) return '';
  const out = [];
  if (r.p != null) {
    const n = r.trend == null ? null : Math.abs(r.trend).toFixed(1);
    out.push(n == null || n === '0.0' ? tr('beaconPressure', { hpa: r.p }) : tr(r.trend < 0 ? 'beaconPressureFalling' : 'beaconPressureRising', { hpa: r.p, n }));
  }
  if (r.speed != null) out.push(tr('beaconWind', { speed: r.speed, from: compass(r.wfrom, true) }));
  if (r.hs != null && r.tp != null && !Number.isNaN(r.sfrom)) out.push(tr('beaconSwell', { hs: r.hs, tp: r.tp, from: compass(r.sfrom, true) }));
  return out.length ? `. ${out.join(' ')}` : '';
}

// ---- The control column: a toggle a row, for that layer on the chart ----
// Each grid cell keeps its own choice on this device (nss.beacon.layers:
// cell -> the first letters of the layers on), saved as it's tapped; a cell
// never opened starts with all three on.
const LAYERS = ['pressure', 'wind', 'swell'], layerBtns = [...document.querySelectorAll('[data-layer]')];
const savedLayers = () => store.get('nss.beacon.layers', {});
function layersFor(id) {
  const s = savedLayers()[id];
  return Object.fromEntries(LAYERS.map((l) => [l, typeof s !== 'string' || s.includes(l[0])]));
}
// The toggles, and the rows whose layer is off greyed (still updating).
function renderLayers() {
  if (!beacon) return;
  for (const b of layerBtns) b.setAttribute('aria-pressed', String(beacon.layers[b.dataset.layer]));
  for (const l of LAYERS) {
    const off = !beacon.layers[l];
    $(`.nss-row[data-row="${l}"]`).toggleAttribute('data-off', off);
    marks[l].toggleAttribute('data-off', off);
    const g = rowsTrack.querySelector(`g[data-row="${l}"]`);
    if (g) { if (off) { g.setAttribute('filter', 'url(#nss-mono)'); g.setAttribute('opacity', '0.4'); } else { g.removeAttribute('filter'); g.removeAttribute('opacity'); } }
  }
}
for (const b of layerBtns) b.addEventListener('click', () => {
  if (!beacon) return;
  const l = b.dataset.layer;
  beacon.layers[l] = !beacon.layers[l];
  const all = savedLayers();
  all[beacon.id] = LAYERS.filter((k) => beacon.layers[k]).map((k) => k[0]).join('');
  store.set('nss.beacon.layers', all);
  renderLayers(); requestDraw(); warm();
});

// ---- The sheet's title row: Copy link, the grip, Close ----
copyBtn.addEventListener('click', async () => {
  if (!beacon) return;
  const link = `${location.origin}${location.pathname}?at=${beacon.lat.toFixed(2)},${beacon.lon.toFixed(2)}&layers=${LAYERS.filter((l) => beacon.layers[l]).map((l) => l[0]).join('') || '-'}`;
  try { await navigator.clipboard.writeText(link); } catch { return; }
  copyBtn.innerHTML = icon('check'); saidEl.textContent = tr('linkCopied');
  setTimeout(() => { copyBtn.innerHTML = icon('share'); saidEl.textContent = ''; }, 1500);
});
$('[data-beacon-close]').addEventListener('click', closeBeacon);
// The grip: tapped, or pulled down far or fast enough, the beacon goes.
let gripPull = null;
grip.addEventListener('pointerdown', (e) => {
  grip.setPointerCapture(e.pointerId);
  gripPull = { y: e.clientY, t: performance.now(), dy: 0 };
  panelEl.style.transition = 'none';
});
grip.addEventListener('pointermove', (e) => {
  if (!gripPull) return;
  gripPull.dy = Math.max(0, e.clientY - gripPull.y);
  panelEl.style.transform = gripPull.dy ? `translateY(${gripPull.dy}px)` : '';
});
const gripEnd = () => {
  const p = gripPull;
  if (!p) return;
  gripPull = null;
  panelEl.style.transition = ''; panelEl.style.transform = '';
  const fast = p.dy > 16 && p.dy / (performance.now() - p.t) > 0.5;
  if (p.dy > 60 || fast || p.dy < 6) closeBeacon();
};
grip.addEventListener('pointerup', gripEnd);
grip.addEventListener('pointercancel', () => { gripPull = null; panelEl.style.transition = ''; panelEl.style.transform = ''; });
// By keyboard, the grip is a button: Enter or Space closes it like a tap.
grip.addEventListener('click', (e) => { if (e.detail === 0) closeBeacon(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && beacon && !sheetOn && !guideOn()) { e.preventDefault(); closeBeacon(); }
});
// The link: ?at=<lat>,<lon> drops the beacon on the nearest sea grid point,
// with Beacons on, and the sender's layers (&layers=, the first letters of
// those on) if it carries them, else the cell's own.
const atQ = (Q.get('at') || '').split(',').map(Number), layersQ = Q.get('layers');
async function openAt() {
  if (atQ.length !== 2 || atQ.some(Number.isNaN) || !grid) return;
  const r = await grid.resolve(atQ[0], atQ[1], 'waves', 30).catch(() => null);
  if (!r || beacon) return;
  const c = grid.cellOf(r.id), [x, y] = grid.lonLatToKm(c.lon, c.lat);
  if (!beaconsOn) { beaconsOn = true; store.set('nss.beacons', true); renderPanel(); }
  dropBeacon({ id: r.id, ...c, x, y }, layersQ == null ? null : Object.fromEntries(LAYERS.map((l) => [l, layersQ.includes(l[0])])));
}

// ---- Hints: what the app teaches (hints.js), one controller for all of it --------------------
// The rules in one place: one hint on screen at a time, never mid-gesture
// (1.5 s of quiet first), one new one a visit (a chain of tips counts as
// one), each shown once. A tip sits beside its control in whichever panel is
// showing; the first touch dims it, and it goes for good when its action is
// done, when it's tapped, or after 6 s with nothing touched. Kept under
// nss.hints.v1, with the release someone first came on (deploy.yml stamps
// index.html's data-release), so a feature's news only reaches people who
// were here before it.
const HINT_IDLE = 1500, HINT_WAIT = 6000;
const RELEASE = document.documentElement.dataset.release || 'dev';
const hs = (() => {
  let s = store.get('nss.hints.v1', null);
  if (!s) {
    // The first time with hints: anyone with something of ours kept came
    // before every release, and keeps the tips they've already seen.
    let before = false;
    try { before = Object.keys(localStorage).some((k) => k.startsWith('nss.')); } catch {}
    const seen = {};
    if (store.get('nss.tip1', false)) seen['tip.timeline.slide'] = 'retired';
    if (store.get('nss.tip2', false)) seen['tip.timeline.reset'] = 'retired';
    s = { firstSeenRelease: before ? '0' : null, tipsOn: true, seen, guideCompleted: false };
  }
  if (s.firstSeenRelease == null && RELEASE !== 'dev') s.firstSeenRelease = RELEASE;
  store.set('nss.hints.v1', s);
  return s;
})();
// What the app does, for hints to listen for: timeline.drag, timeline.reset,
// map.zoom, swell.measure, panel.changed.
const heard = {};
const emit = (name) => (heard[name] || []).forEach((f) => f());
// This visit's one new hint (the chain it starts), kept through a reload.
let hintSpent = null;
try { hintSpent = sessionStorage.getItem('nss.hints.shown'); } catch {}
const hintById = Object.fromEntries(HINTS.map((h) => [h.id, h]));
const chainOf = (h) => ((h.when || '').startsWith('after:') ? chainOf(hintById[h.when.slice(6)]) : h.id);
let hintOn = null, hintCard = false, hintFading = false, hintT = 0, hintGoT = 0, tagDown = null;
// The sheets opened this visit: a light on the way into one stops pinging.
const hintOpened = new Set();
// A new feature, for someone who came before it (not someone new to a
// development copy, who came on no release), until it's used or tips go off.
const hintNew = (h) => hs.tipsOn && hs.seen[h.id] !== 'retired' && hs.firstSeenRelease != null && hs.firstSeenRelease < h.since;
function hintMet(h) {
  if (h.type === 'new') return hintNew(h);
  if (h.when.startsWith('after:')) return hs.seen[h.when.slice(6)] === 'retired';
  if (h.when.startsWith('measure:')) return band === 'swell' && swellVar === h.when.slice(8);
  if (h.when === 'beacons-on') return beaconsOn && !beacon && !!crossSpot;
  return h.when === 'first-load' && !!man;
}
const hintDue = (h) => hs.tipsOn && !hs.seen[h.id] && (!hintSpent || hintSpent === chainOf(h)) && hintMet(h);
const hintBusy = () => !!(ptrs.size || drag || tl.moving || sheetOn || guideOn() || beacon);
const floatTag = $('[data-tip-float]'), newTag = $('[data-new-tag]'), card = $('[data-hint-card]');
const gotIt = card.querySelector('[data-got-it]'), showMe = card.querySelector('[data-show-me]');
// What Show me does.
const HINT_ACTIONS = { 'open-settings:panel': () => openSheet('settings', '[data-set="panel"] [aria-pressed="true"]'), 'beacons-on': () => setBeacons(true, true) };
// The control a hint is about, in the panel showing.
const hintEl = (h) => [...document.querySelectorAll(`[data-hint-target="${h.target}"]`)].find((el) => !el.closest('[data-away], [hidden]'));
// Beside what it's about, notched to it and kept on the screen: over it, off
// the docked column; or, for something in the column, beside the column,
// level with it.
function placeBy(box, pt, notch) {
  const r = pt.getBoundingClientRect(), c = columnEl.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
  const cardNotch = notch.classList.contains('nss-card-notch'), half = cardNotch ? 5 : 4;
  let x, y;
  if (sideOn() && r.left >= c.left && r.right <= c.right) {
    const mid = r.top + r.height / 2, right = hand === 'right';
    x = right ? c.left - 12 - w : c.right + 12;
    y = Math.max(12, Math.min(innerHeight - 12 - h, mid - h / 2));
    Object.assign(notch.style, { left: `${right ? w - half : -half}px`, top: `${mid - y - half}px`, bottom: 'auto', transform: cardNotch ? `rotate(${right ? -45 : 135}deg)` : '' });
  } else {
    const mid = r.left + r.width / 2;
    let lo = 12, hi = innerWidth - 12;
    if (sideOn()) { if (mid < c.left) hi = c.left - 12; else lo = c.right + 12; }
    x = Math.max(lo, Math.min(hi - w, mid - w / 2));
    y = r.top - h - 10;
    Object.assign(notch.style, { left: `${mid - x - half}px`, top: '', bottom: '', transform: '' });
  }
  box.style.left = `${x}px`; box.style.top = `${y}px`;
}
// A new feature's lights, on every control on the way to it: pinging while
// it's announced, until the sheet past each one's been opened; steady
// otherwise. Changed only where they change, so a ping isn't restarted.
function renderLights() {
  const want = new Map();
  for (const h of HINTS) {
    if (h.type !== 'new' || !hintNew(h)) continue;
    const announcing = hintOn === h && !hintCard;
    h.path.forEach((id, i) => {
      const next = h.path[i + 1] && document.querySelector(`[data-hint-target="${h.path[i + 1]}"]`);
      const past = next && next.closest('[data-sheet]');
      const ping = announcing && !(past && hintOpened.has(past.dataset.sheet));
      document.querySelectorAll(`[data-hint-target="${id}"]`).forEach((el) => want.set(el, want.get(el) || ping));
    });
  }
  document.querySelectorAll('[data-hint-target]').forEach((el) => {
    let light = el.querySelector(':scope > .nss-light');
    if (!want.has(el) && !light) return;
    if (!want.has(el)) light.remove();
    else {
      if (!light) {
        light = el.appendChild(document.createElement('span'));
        light.className = 'nss-light';
        // Said with the control's name, or in words of its own.
        if (el.dataset.tLabel) light.setAttribute('aria-hidden', 'true'); else light.innerHTML = '<span class="vh"></span>';
      }
      light.classList.toggle('nss-light--ping', want.get(el));
      if (!el.dataset.tLabel) light.firstChild.textContent = tr('somethingNew');
    }
    if (el.dataset.tLabel) el.setAttribute('aria-label', tr(el.dataset.tLabel) + (want.has(el) ? tr('somethingNew') : ''));
  });
}
function renderHint() {
  // Gone from under it (another band, say): put back for later, not seen.
  if (hintOn && !hintMet(hintOn)) { hintOn = null; hintCard = false; clearTimeout(hintGoT); }
  renderLights();
  const el = hintOn && hintEl(hintOn), tip = !!el && hintOn.type === 'tip', news = !!el && hintOn.type === 'new';
  // A tip in its control (the timeline's, on the needle's arrow)...
  document.querySelectorAll('[data-hint-target] [data-tip]').forEach((tag) => {
    const on = tip && !hintOn.point && tag.closest('[data-hint-target]') === el;
    tag.hidden = !on;
    if (on) { tag.innerHTML = icon(hintOn.icon) + tr(hintOn.label); tag.toggleAttribute('data-fading', hintFading); }
  });
  // ...or floating over the part it points at.
  const pt = tip && hintOn.point && el.querySelector(`[data-hint-point="${hintOn.point}"]`);
  crossSpotEl.toggleAttribute('data-on', !!pt && hintOn.target === 'cross');
  floatTag.hidden = !pt;
  if (pt) {
    floatTag.innerHTML = icon(hintOn.icon) + tr(hintOn.label) + '<span class="nss-tip-notch"></span>';
    floatTag.toggleAttribute('data-fading', hintFading);
    placeBy(floatTag, pt, floatTag.lastChild);
  }
  // A new feature's tag, or the card it opened.
  // (Docked, a feature that asks for it has its light alone.)
  const tagged = news && !(hintOn.tagOpenOnly && sideOn());
  newTag.hidden = !tagged || hintCard;
  if (tagged && !hintCard) {
    newTag.innerHTML = '<span class="nss-new-tag-light" aria-hidden="true"></span>' + tr('newTag', { name: tr(hintOn.name) }) +
      icon('chevron', ' nss-icon--sm') + '<span class="nss-tip-notch" aria-hidden="true"></span>';
    placeBy(newTag, el, newTag.lastChild);
  }
  card.hidden = !news || !hintCard;
  if (news && hintCard) placeBy(card, el, card.lastElementChild);
}
// Quiet from now: the next hint, if one's due, once it's lasted.
function hintWait() { clearTimeout(hintT); hintT = setTimeout(nextHint, HINT_IDLE); }
function nextHint() {
  if (hintOn) return;
  if (hintBusy()) { hintWait(); return; }
  const h = HINTS.find(hintDue);
  if (!h) return;
  if (!hintSpent) { hintSpent = chainOf(h); try { sessionStorage.setItem('nss.hints.shown', hintSpent); } catch {} }
  hintOn = h; hintCard = false; hintFading = false; renderHint();
  hintGoT = setTimeout(hintLapsed, HINT_WAIT);
}
// Gone: for good, or (a new feature not taken up) just its light left on.
function hintGo(state = 'retired') {
  if (!hintOn) return;
  const h = hintOn, focused = card.contains(document.activeElement);
  hs.seen[h.id] = state; store.set('nss.hints.v1', hs);
  hintOn = null; hintCard = false; clearTimeout(hintGoT); renderHint(); hintWait();
  if (focused) { const el = hintEl(h); if (el) el.focus({ preventScroll: true }); }
}
const hintLapsed = () => hintGo(hintOn && hintOn.type === 'new' ? 'quiet' : 'retired');
// A touch anywhere: a tip dims, a tag waits 6 s more, a card tapped away
// from closes to its light, and the quiet starts over.
function hintTouched(e) {
  if (hintCard && e.type === 'pointerdown' && !card.contains(e.target)) hintGo('quiet');
  if (hintOn && !hintCard) {
    if (hintOn.type === 'tip' && !hintFading) { hintFading = true; renderHint(); }
    clearTimeout(hintGoT); hintGoT = setTimeout(hintLapsed, HINT_WAIT);
  }
  hintWait();
}
// Done what a hint says, shown or not yet: it's not needed.
for (const h of HINTS) {
  (heard[h.doneEvent] ||= []).push(() => {
    if (hintOn === h) hintGo();
    else if (hs.seen[h.id] !== 'retired') { hs.seen[h.id] = 'retired'; store.set('nss.hints.v1', hs); renderHint(); }
  });
}
// The tag opens its card: focus in it, kept there; Escape closes it to its light.
newTag.addEventListener('click', () => {
  if (!hintOn || hintOn.type !== 'new') return;
  const h = hintOn;
  clearTimeout(hintGoT); hintCard = true;
  card.setAttribute('aria-label', tr('newTag', { name: tr(h.name) }));
  card.querySelector('[data-card-kicker]').textContent = tr(h.kicker);
  card.querySelector('[data-card-title]').textContent = tr(h.title);
  card.querySelector('[data-card-body]').textContent = tr(h.body);
  showMe.hidden = !h.action;
  renderHint();
  (h.action ? showMe : gotIt).focus({ preventScroll: true });
});
gotIt.addEventListener('click', () => hintGo());
showMe.addEventListener('click', () => { const h = hintOn; hintGo(); HINT_ACTIONS[h.action](); });
addEventListener('keydown', (e) => {
  if (!hintCard) return;
  if (e.key === 'Escape') { e.preventDefault(); hintGo('quiet'); return; }
  if (e.key !== 'Tab') return;
  const f = [gotIt, showMe].filter((b) => !b.hidden), i = f.indexOf(document.activeElement);
  if (i < 0 || (e.shiftKey ? i === 0 : i === f.length - 1)) { e.preventDefault(); f[e.shiftKey ? f.length - 1 : 0].focus(); }
});
// Menu › Settings: tips off (every one gone, and none new), on, or all of
// them again from the start, the next one once the menu's closed.
function setTips(on) {
  hs.tipsOn = on;
  if (!on) { for (const h of HINTS) hs.seen[h.id] = 'retired'; hintOn = null; hintCard = false; clearTimeout(hintGoT); }
  store.set('nss.hints.v1', hs); renderSettings(); renderHint();
}
const tipsAgain = $('[data-tips-again]');
tipsAgain.addEventListener('click', () => {
  hs.seen = {}; hs.tipsOn = true; hintSpent = null;
  try { sessionStorage.removeItem('nss.hints.shown'); } catch {}
  store.set('nss.hints.v1', hs); renderSettings(); renderHint();
  tipsAgain.querySelector('.nss-menu-sub').textContent = tr('tipsAgainDone');
});
for (const k of ['pointerdown', 'wheel', 'keydown']) addEventListener(k, hintTouched, { capture: true, passive: true });
// A tip tapped (not dragged from): gone.
document.querySelectorAll('[data-tip]').forEach((tag) => tag.addEventListener('pointerdown', (e) => {
  tagDown = { x: e.clientX, y: e.clientY, t: performance.now() };
}));
addEventListener('pointerup', (e) => {
  const d = tagDown;
  tagDown = null;
  if (d && hintOn && performance.now() - d.t < 300 && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 6) hintGo();
  hintWait();
}, { capture: true, passive: true });

// ---- The Guide (Menu › Guide): a tour of the chart, one control lit at a time (hints.js) -------
// Only ever when asked. The chart dims under the panel and the panel dims in
// itself, but for the lit control, which stays live; the step card sits just
// above the open panel (docked, beside the column, level with what's lit, or
// over the key), notched to it. Next always works, and a Try it is ticked
// once it's done. Closed (✕, Escape, back) or done, the band it put on is
// put back, and the tips it's taught go. Tips wait while it's on.
const guideCard = $('[data-guide-card]'), guideChart = $('[data-guide-scrim]');
const guideScrims = [panelEl, columnEl].map((p) => {
  const s = p.appendChild(document.createElement('div'));
  s.className = 'nss-guide-scrim'; s.hidden = true;
  return s;
});
const gBack = guideCard.querySelector('[data-guide-back]'), gNext = guideCard.querySelector('[data-guide-next]');
const gTry = guideCard.querySelector('[data-guide-try]'), gNotch = guideCard.lastElementChild;
let guideStep = -1, guideBand = null, guideTried = new Set();
function guideOn() { return guideStep >= 0; }
function startGuide() {
  if (hintOn) { hintOn = null; hintCard = false; clearTimeout(hintGoT); renderHint(); }
  guideStep = 0; guideBand = null; guideTried = new Set();
  try { history.pushState({ guide: true }, ''); } catch {}
  renderGuide();
  gNext.focus({ preventScroll: true });
}
function endGuide(completed) {
  if (!guideOn()) return;
  guideStep = -1;
  document.querySelectorAll('.nss-spot').forEach((el) => el.classList.remove('nss-spot'));
  guideCard.hidden = guideChart.hidden = true;
  guideScrims.forEach((s) => { s.hidden = true; });
  columnEl.removeAttribute('data-guide');
  if (guideBand) { setBand(guideBand); guideBand = null; }
  for (const h of HINTS) if (h.type === 'tip') hs.seen[h.id] = 'retired';
  if (completed) hs.guideCompleted = true;
  store.set('nss.hints.v1', hs);
  if (history.state && history.state.guide) history.back();
  if (!sheetOn) menuBtn().focus({ preventScroll: true });
  hintWait();
}
function renderGuide() {
  const st = GUIDE[guideStep], last = guideStep === GUIDE.length - 1, chart = st.target === 'chart';
  if (st.band && band !== st.band) { guideBand = guideBand || band; setBand(st.band); setTimeout(() => guideOn() && placeGuide(), 260); }
  document.querySelectorAll('.nss-spot').forEach((el) => el.classList.remove('nss-spot'));
  const el = hintEl(st);
  if (el && !chart) el.classList.add('nss-spot');
  guideChart.hidden = chart;
  guideScrims.forEach((s) => { s.hidden = false; });
  columnEl.setAttribute('data-guide', '');
  guideCard.setAttribute('aria-label', tr('guideLabel', { n: guideStep + 1, total: GUIDE.length }));
  guideCard.querySelector('.nss-guide-ticks').innerHTML = GUIDE.map((_, i) =>
    `<span${i < guideStep ? ' data-state="done"' : i === guideStep ? ' data-state="current"' : ''}></span>`).join('');
  guideCard.querySelector('[data-guide-count]').textContent = `${guideStep + 1} / ${GUIDE.length}`;
  guideCard.querySelector('[data-guide-title]').textContent = tr(st.title);
  guideCard.querySelector('[data-guide-body]').textContent = tr(st.body);
  gTry.hidden = !st.tryIt;
  if (st.tryIt) {
    const done = guideTried.has(guideStep);
    gTry.toggleAttribute('data-done', done);
    gTry.firstElementChild.textContent = tr(done ? 'done' : 'tryIt');
    gTry.lastElementChild.textContent = tr(st.tryIt);
  }
  gBack.hidden = guideStep === 0;
  gNext.textContent = tr(last ? 'done' : 'next');
  guideCard.hidden = false;
  placeGuide();
}
// Above the open panel, notched to what's lit; docked, beside the column:
// level with what's lit in it, over what's lit beside it (the key), or at
// the bottom for the chart itself.
function placeGuide() {
  const st = GUIDE[guideStep], el = st.target !== 'chart' && hintEl(st), r = el && el.getBoundingClientRect();
  const c = columnEl.getBoundingClientRect(), right = hand === 'right';
  const side = sideOn(), w = side ? (right ? c.left : innerWidth - c.right) - 24 : innerWidth - 24, x = side && !right ? c.right + 12 : 12;
  Object.assign(guideCard.style, { left: `${x}px`, right: 'auto', width: `${w}px` });
  const h = guideCard.offsetHeight, below = (cx) => Object.assign(gNotch.style, {
    left: `${Math.max(12, Math.min(w - 22, cx - x - 5))}px`, top: '', bottom: '', transform: '' });
  let y;
  gNotch.hidden = !r;
  if (!side) { y = panelEl.getBoundingClientRect().top - 12 - h; if (r) below(r.left + r.width / 2); }
  else if (r && r.left >= c.left - 1 && r.right <= c.right + 1) {
    const mid = r.top + r.height / 2;
    y = Math.max(12, Math.min(innerHeight - 12 - h, mid - h / 2));
    Object.assign(gNotch.style, { left: `${right ? w - 6 : -6}px`, top: `${mid - y - 5}px`, bottom: 'auto', transform: `rotate(${right ? -45 : 135}deg)` });
  } else if (r) { y = r.top - 12 - h; below(r.left + r.width / 2); }
  else y = innerHeight - 12 - h;
  guideCard.style.top = `${Math.max(12, y)}px`;
}
$('[data-guide]').addEventListener('click', () => { closeSheet(); startGuide(); });
gNext.addEventListener('click', () => { if (guideStep === GUIDE.length - 1) endGuide(true); else { guideStep++; renderGuide(); } });
gBack.addEventListener('click', () => { if (guideStep > 0) { guideStep--; renderGuide(); gNext.focus({ preventScroll: true }); } });
guideCard.querySelector('[data-guide-close]').addEventListener('click', () => endGuide(false));
// The system's back gesture closes it.
addEventListener('popstate', () => endGuide(false));
// Try it: done on the real thing.
for (const st of GUIDE) {
  if (!st.doneEvent) continue;
  (heard[st.doneEvent] ||= []).push(() => {
    if (guideOn() && GUIDE[guideStep] === st) { guideTried.add(guideStep); renderGuide(); }
  });
}
// Escape closes it; focus goes round the card and the lit control.
addEventListener('keydown', (e) => {
  if (!guideOn() || sheetOn) return;
  if (e.key === 'Escape') { e.preventDefault(); endGuide(false); return; }
  if (e.key !== 'Tab') return;
  const spot = document.querySelector('.nss-spot');
  const f = [...(spot ? [spot, ...spot.querySelectorAll('button, [tabindex]')] : []), ...guideCard.querySelectorAll('button')]
    .filter((b) => b.tabIndex >= 0 && !b.disabled && !b.closest('[hidden]') && b.getClientRects().length);
  const i = f.indexOf(document.activeElement);
  if (i < 0 || (e.shiftKey ? i === 0 : i === f.length - 1)) { e.preventDefault(); f[e.shiftKey ? f.length - 1 : 0].focus(); }
});

// ---- ?debug=1: where the app thinks it is, and the space the phone keeps -----------------
if (Q.has('debug')) {
  const probe = document.createElement('div');
  probe.style.cssText = 'position:fixed;visibility:hidden;padding:env(safe-area-inset-top,0px) 0 env(safe-area-inset-bottom,0px)';
  const out = document.createElement('pre');
  out.style.cssText = 'position:fixed;left:8px;top:calc(8px + env(safe-area-inset-top,0px));z-index:9;margin:0;padding:6px 8px;' +
    'background:var(--ui-display);color:var(--ui-display-ink);font:500 10px/1.4 var(--font-mono);border-radius:var(--radius-card);pointer-events:none';
  document.body.append(probe, out);
  let fps = 0, n = 0, t0 = 0, prev = 0;
  const show = () => {
    const cs = getComputedStyle(probe), vv = window.visualViewport;
    out.textContent = [location.host, `surface ${document.documentElement.dataset.surface}${document.documentElement.hasAttribute('data-short') ? ', short' : ''}`,
      `safe top ${cs.paddingTop}, bottom ${cs.paddingBottom}`,
      `window ${innerWidth}×${innerHeight}`, vv ? `visible ${Math.round(vv.width)}×${Math.round(vv.height)}` : '',
      `screen ${screen.width}×${screen.height}`, ...timelineLines(), ...cellLines()].filter(Boolean).join('\n');
  };
  // The grid: the cell under the last tap, its own numbers from the run's
  // cell tile at the needle's hour, and the frame's 25 km node nearest it.
  let pick = null;
  const beaconTap = onTap;
  onTap = (cx, cy) => {
    beaconTap(cx, cy);
    if (!grid || !man) return;
    const wx = view.x + (cx - W / 2) / view.k, wy = view.y - (cy - Hs / 2) / view.k, [lon, lat] = grid.kmToLonLat(wx, wy);
    const p = pick = { lon, lat, wx, wy, id: grid.cellAt(lon, lat), s: undefined };
    grid.series(p.id).then((s) => { p.s = s; show(); }).catch((e) => { p.s = null; p.err = e.message; show(); });
    show();
  };
  const ll = (lat, lon) => `${Math.abs(lat).toFixed(2)}${lat < 0 ? 'S' : 'N'} ${Math.abs(lon).toFixed(2)}${lon < 0 ? 'W' : 'E'}`;
  function cellLines() {
    if (!pick || !man) return grid ? ['cell: tap the chart'] : [];
    const p = pick, c = grid.cellOf(p.id), out = [`cell ${p.id} (${ll(c.lat, c.lon)}), tapped ${ll(p.lat, p.lon)}`];
    const f = (x, d = 1) => (Number.isNaN(x) ? '–' : x.toFixed(d)), i = idx;
    if (p.s === undefined) out.push('  loading its tile');
    else if (!p.s) out.push(p.err ? `  no tile: ${p.err}` : '  outside the cell tiles');
    else {
      const s = p.s, from = (deg) => (Number.isNaN(deg) ? '–' : Math.round(deg) + '°');
      const wind = Math.hypot(s.u[i], s.v[i]), wfrom = (Math.atan2(-s.u[i], -s.v[i]) * 180 / Math.PI + 360) % 360;
      out.push(s.sea ? `  +${s.steps[i]} h sea: Hs ${f(s.hs[i])} m, peak ${f(s.tp[i])} s from ${from(s.dp[i])}, longest ${f(s.tl[i])} s from ${from(s.dl[i])}`
        : `  +${s.steps[i]} h land: wind and pressure only`, `  wind ${f(wind)} m/s from ${from(wfrom)}, ${f(s.p[i])} hPa`);
    }
    const d = frames[i], S = man.grids.s, sq = man.square;
    const gj = Math.round((p.wx - sq.x0) / (sq.x1 - sq.x0) * (S - 1)), gi = Math.round((sq.y0 - p.wy) / (sq.y0 - sq.y1) * (S - 1));
    if (d && gi >= 0 && gj >= 0 && gi < S && gj < S) {
      const h = d.h[gi * S + gj], t = d.t[gi * S + gj];
      out.push(`  frame's 25 km node: ${h === 255 ? 'no sea' : `Hs ${(h / man.scale.h).toFixed(1)} m, longest ${(t / man.scale.t).toFixed(1)} s`}`);
    }
    return out;
  }
  show(); addEventListener('resize', show); window.visualViewport && visualViewport.addEventListener('resize', show);
  // The timeline: whether iOS let the page have the whole touch, how many
  // moves reached it, how slow the slowest frame was while it moved, and how
  // the release was judged.
  (function tick(t) {
    if (prev && tl.moving && tlDbg.cur) tlDbg.cur.slowest = Math.max(tlDbg.cur.slowest, t - prev);
    prev = t; n++;
    if (t - t0 > 1000) { fps = Math.round(n * 1000 / (t - t0)); n = 0; t0 = t; show(); }
    requestAnimationFrame(tick);
  })(0);
  for (const T of TL) {
    for (const k of ['touchstart', 'touchmove', 'touchend', 'touchcancel']) {
      T.el.addEventListener(k, (e) => {
        const c = tlDbg.cur; if (!c) return;
        if (k === 'touchmove') c.touches++;
        if (k === 'touchcancel') c.touchCancel = true;
      }, { passive: true });
    }
  }
  function timelineLines() {
    const c = tlDbg.last, f = (x, d = 0) => (x == null ? '–' : (+x).toFixed(d));
    return [`frame rate ${fps}/s${reduced.matches ? ', reduce motion ON' : ''}, smooth-move fix ${typeof movingFrame === 'function' ? 'in' : 'missing'}`,
      c ? `last drag: ${c.moves} moves (${c.merged} with merged), ${c.touches} touchmoves${c.touchCancel ? ', TOUCH CANCELLED' : ''}` : 'last drag: –',
      c ? `  ended ${c.end}, gap ${f(c.gap)} ms (stamped ${f(c.stampGap)}), over ${f(c.span)} ms, speed ${f(c.v, 3)}, ${c.flick ? 'flicked' : 'no flick'}` : '',
      c ? `  slowest frame ${f(c.slowest)} ms, built ${c.builds}, stamp ${c.raw > 1e11 ? 'epoch' : 'page'}` : ''];
  }
}

// ---- Start -------------------------------------------------------------------------------
readTokens();
renderPanel();
setHand(hand, true);
setDocked(docked, true);
resize();
requestAnimationFrame(() => requestAnimationFrame(() => document.documentElement.classList.remove('still')));
document.fonts && document.fonts.ready.then(requestDraw);
document.fonts && document.fonts.load(`400 10px ${FONT}`).then(requestDraw).catch(() => {});
renderStatus();
renderLangs();
if (!langAsked) askLang();
refreshManifest();
if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('sw.js').catch(() => {});
