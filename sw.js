/* The app's service worker: keeps the charts on the phone.

   A run's chart frames (and its ice, grid and swell window) never change once
   drawn, and each one's address names its run, so each is downloaded once and
   kept; when a newer run's frames arrive, the older run's are cleared. The
   page itself, the charts' manifest and the latest readings come from the
   network when there is one and from the last copy kept when there isn't, so
   the app still opens, with the last charts, where there's no signal.
   Registered by index.html. */
const CHARTS = 'https://raw.githubusercontent.com/mattkirwan/north-sea-charts/charts/';
const DATA = 'https://raw.githubusercontent.com/mattkirwan/north-sea-charts/data/';
const FRAMES = 'nsv-frames-v1', LATEST = 'nsv-latest-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k !== FRAMES && k !== LATEST) await caches.delete(k);
  await self.clients.claim();
})()));

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.href.startsWith(CHARTS) && url.searchParams.has('run')) e.respondWith(frame(e, url));
  else if (req.mode === 'navigate' && url.origin === location.origin) e.respondWith(latest(req, url.origin + url.pathname));
  else if (url.href.startsWith(CHARTS + 'manifest.json') || url.href.startsWith(DATA)) e.respondWith(latest(req, url.origin + url.pathname));
});

// A run's file: the copy kept, or downloaded and kept. Reload charts in
// Settings adds v= to the address, which downloads it again.
async function frame(e, url) {
  const run = url.searchParams.get('run'), fresh = url.searchParams.has('v');
  url.searchParams.delete('v');
  const key = url.href, cache = await caches.open(FRAMES);
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
  if (res.ok) e.waitUntil(cache.put(key, res.clone()).then(() => tidy(cache, run)));
  return res;
}

// Clear the files of runs older than this one, once per new run.
let tidied = '';
async function tidy(cache, run) {
  if (run <= tidied) return;
  tidied = run;
  for (const req of await cache.keys()) {
    const r = new URL(req.url).searchParams.get('run');
    if (r && r < run) await cache.delete(req);
  }
}

// The network's copy, kept for next time; the kept copy when there's no network.
async function latest(req, key) {
  const cache = await caches.open(LATEST);
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
