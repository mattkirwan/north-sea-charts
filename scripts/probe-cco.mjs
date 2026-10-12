// Temporary: see what the Coastal Monitoring (CCO) API returns for the
// latest waves, so the collector can read Whitby's buoy.
const KEY = 'd36f6f6fcf2468bec6d79fe781ee6a03';
const HEAD = { Referer: 'https://mattkirwan.github.io/', Accept: 'application/json' };
const show = async (u) => {
  try {
    const r = await fetch(u, { headers: HEAD, signal: AbortSignal.timeout(60e3) });
    const t = await r.text();
    console.log(`\n== ${r.status} ${r.headers.get('content-type')} ${r.headers.get('access-control-allow-origin') ?? '(no CORS header)'}\n${u.replace(KEY, 'KEY')}\n${t.slice(0, 2500)}`);
    return t;
  } catch (e) { console.log(`\n== failed ${u.replace(KEY, 'KEY')}: ${e.message}`); return ''; }
};
await show('https://coastalmonitoring.org/ccoresources/api/');
const base = 'https://coastalmonitoring.org/observations/waves/latest';
await show(`${base}?key=${KEY}`);
await show(`${base}.json?key=${KEY}`);
await show(`${base}?key=${KEY}&format=json`);
await show(`${base}?key=${KEY}&sensor=Whitby`);
await show(`${base}?key=${KEY}&sensor=Whitby&format=json`);
