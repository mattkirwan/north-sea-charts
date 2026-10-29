/* The app's service worker: keeps the charts on the phone.

   The chart screen (index.html, app.js): each run's frames (frames branch)
   are kept the same way as the old charts below, in their own cache, and the
   app's own files, the base map and the font come from the network when
   there is one and from the last copy kept when there isn't. The old app
   (legacy.html, behind the prediction flag) works as it always has:

   A run's chart frames (and its cell tiles, ice, grid and swell window)
   never change once drawn, and each one's address names its run, so each is
   downloaded once and kept; when a newer run's frames arrive, the older
   run's are cleared. The page itself, the charts' manifest and the latest
   readings come from the network when there is one and from the last copy
   kept when there isn't, so the app still opens, with the last charts,
   where there's no signal.
   Registered by index.html. */
const CHARTS = 'https://raw.githubusercontent.com/mattkirwan/north-sea-charts/charts/';
const DATA = 'https://raw.githubusercontent.com/mattkirwan/north-sea-charts/data/';
const FRAMES_NEW = 'https://raw.githubusercontent.com/mattkirwan/north-sea-charts/frames/';
const FONTS = ['https://fonts.googleapis.com/', 'https://fonts.gstatic.com/'];
const FRAMES = 'nsv-frames-v1', LATEST = 'nsv-latest-v1', NSS_FRAMES = 'nss-frames-v1', NSS_STATIC = 'nss-static-v1';
const KEEP = [FRAMES, LATEST, NSS_FRAMES, NSS_STATIC];

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (!KEEP.includes(k)) await caches.delete(k);
  await self.clients.claim();
})()));

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.href.startsWith(CHARTS) && url.searchParams.has('run')) e.respondWith(frame(e, url));
  else if ((/\/f\d{3}\.bin\.gz$/.test(url.pathname) || /\/cells\/.+\.bin\.gz$/.test(url.pathname)) && url.searchParams.has('run'))
    e.respondWith(frame(e, url, NSS_FRAMES));
  else if (req.mode === 'navigate' && url.origin === location.origin) e.respondWith(latest(req, url.origin + url.pathname));
  else if (url.href.startsWith(CHARTS + 'manifest.json') || url.href.startsWith(DATA) || url.href.startsWith(FRAMES_NEW + 'manifest.json') || url.href.startsWith(FRAMES_NEW + 'ice.json') ||
           (url.origin === location.origin && url.pathname.endsWith('/manifest.json')))
    e.respondWith(latest(req, url.origin + url.pathname));
  // The app's own files, ?v= (the deploy, index.html) or not, kept under
  // their path, so a deploy's copy replaces the last one's. Checked with the
  // server every time, past the browser's cache: a host that lets the browser
  // keep scripts for hours (Cloudflare's Browser Cache TTL) would otherwise
  // pair a new page with the last deploy's app.js.
  else if (url.origin === location.origin && (!url.search || [...url.searchParams.keys()].join() === 'v'))
    e.respondWith(latest(new Request(req.url, { cache: 'no-cache' }), url.origin + url.pathname, NSS_STATIC));
  else if (FONTS.some((f) => url.href.startsWith(f))) e.respondWith(kept(req, NSS_STATIC));
});

// A run's file: the copy kept, or downloaded and kept. Reload charts in
// Settings adds v= to the address, which downloads it again.
async function frame(e, url, name = FRAMES) {
  const run = url.searchParams.get('run'), fresh = url.searchParams.has('v');
  url.searchParams.delete('v');
  const key = url.href, cache = await caches.open(name);
  if (!fresh) {
    const kept = await cache.match(key);
    if (kept) return kept;
  }
  let res;
  try {
    // Asked for in CORS mode (GitHub allows it) so the copy kept is readable
    // and stored at its true size, not padded as an opaque response would be.
    res = await fetch(key, { mode: 'cors', credentials: 'omit', cache: fresh ? 'reload' : 'default' });
  } catch {
    return fetch(e.request);
  }
  if (res.ok) e.waitUntil(cache.put(key, res.clone()).then(() => tidy(cache, run, name)));
  return res;
}

// Clear the files of runs older than this one, once per new run.
const tidied = {};
async function tidy(cache, run, name) {
  if (tidied[name] && run <= tidied[name]) return;
  tidied[name] = run;
  for (const req of await cache.keys()) {
    const r = new URL(req.url).searchParams.get('run');
    if (r && r < run) await cache.delete(req);
  }
}

// The network's copy, kept for next time; the kept copy when there's no network.
async function latest(req, key, name = LATEST) {
  const cache = await caches.open(name);
  try {
    const res = await fetch(req);
    if (res.ok && !res.redirected) await cache.put(key, res.clone());
    return res;
  } catch (err) {
    const kept = await cache.match(key);
    if (kept) return kept;
    throw err;
  }
}

// The kept copy if there is one (fonts never change at their address).
async function kept(req, name) {
  const cache = await caches.open(name), hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok || res.type === 'opaque') await cache.put(req, res.clone());
  return res;
}
