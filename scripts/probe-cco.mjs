// Temporary: list what the Coastal Monitoring API offers for a wave buoy.
const KEY = process.env.CCO_API_KEY;
const H = { Referer: 'https://mattkirwan.github.io/', Accept: 'application/json, text/plain, */*' };
const show = async (label, url) => {
  try {
    const r = await fetch(url.replace('KEY', KEY), { headers: H });
    const t = await r.text();
    console.log(`\n== ${label} ${r.status} ${r.headers.get('content-type')} ${t.length} bytes`);
    console.log(t.slice(0, 2500).replaceAll(KEY, '***'));
  } catch (e) { console.log(`\n== ${label} failed ${e.message}`); }
};
await show('latest', 'https://coastalmonitoring.org/observations/waves/latest?key=KEY&format=json');
for (const u of ['https://coastalmonitoring.org/ccoresources/api/', 'https://coastalmonitoring.org/observations/swagger.json',
  'https://coastalmonitoring.org/observations/openapi.json', 'https://coastalmonitoring.org/observations/docs',
  'https://coastalmonitoring.org/observations/swagger', 'https://coastalmonitoring.org/observations/']) await show(u, u);
