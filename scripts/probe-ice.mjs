// Temporary: which sea-ice sources answer, and what they offer.
const show = async (u, n = 1500) => {
  try {
    const r = await fetch(u, { signal: AbortSignal.timeout(30e3) });
    const t = await r.text();
    console.log(`\n== ${r.status} ${r.headers.get('content-type')} ${t.length} bytes  ${u}`);
    console.log(t.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, n));
  } catch (e) { console.log(`\n== failed ${e.message}  ${u}`); }
};
await show('https://cryo.met.no/sites/cryo/files/latest/');
await show('https://cryo.met.no/en/latest-ice-charts', 2500);
await show('https://thredds.met.no/thredds/catalog/osisaf/met.no/ice/conc/2026/10/catalog.html', 2500);
await show('https://thredds.met.no/thredds/catalog/osisaf/met.no/ice/catalog.html', 2000);
await show('https://data.seaice.uni-bremen.de/amsr2/asi_daygrid_swath/n3125/2026/oct/Arctic3125/', 2000);
await show('https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/', 800);
