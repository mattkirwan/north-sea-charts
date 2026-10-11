// Temporary: find Cefas WaveNet's open near-real-time feed (which has wave
// period, unlike the platforms NDBC relays) and print what it looks like.
const show = async (u) => {
  try {
    const r = await fetch(u, { signal: AbortSignal.timeout(60e3) });
    const t = await r.text();
    console.log(`\n== ${r.status} ${r.headers.get('content-type')} ${u}\n${t.slice(0, 1500)}`);
    return t;
  } catch (e) { console.log(`\n== failed ${u}: ${e.message}`); return ''; }
};
const ids = ['2bb869b0-6eff-4e0b-b873-8043f98aa9dd'];
for (const id of ids) {
  const t = await show(`https://data.gov.uk/api/action/package_show?id=${id}`);
  try {
    const pkg = JSON.parse(t).result;
    console.log('\nTitle:', pkg.title, '\nLicence:', pkg.license_title);
    for (const r of pkg.resources || []) {
      console.log(`\nResource: ${r.name} | ${r.format} | ${r.url}`);
      await show(r.url);
    }
  } catch (e) { console.log('parse failed', e.message); }
}
