// Temporary: what the Coastal Monitoring API documents.
const r = await fetch('https://coastalmonitoring.org/ccoresources/api/', { headers: { Referer: 'https://mattkirwan.github.io/' } });
const text = (await r.text()).replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/g, ' ').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n');
const i = text.search(/API v1/);
console.log(text.slice(Math.max(0, i), i + 9000));
console.log('\n--- lines mentioning spectra/partition/swell:');
for (const l of text.split('\n')) if (/spectr|partition|swell|endpoint|observations\//i.test(l)) console.log(l.trim().slice(0, 300));
