// Temporary: the Norwegian Ice Service chart files, and what's inside.
import { execSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
const page = await (await fetch('https://cryo.met.no/en/latest-ice-charts')).text();
const links = [...new Set([...page.matchAll(/href="([^"]+)"/g)].map((m) => m[1]).filter((h) => /shp|shx|dbf|prj|zip|api|\.png|\.pdf|sigrid/i.test(h)))];
console.log(links.join('\n'));
const zip = links.find((h) => /zip/i.test(h) && !/antarc/i.test(h));
const shp = links.find((h) => /\.shp/i.test(h));
for (const u of [zip, shp].filter(Boolean)) {
  const url = new URL(u, 'https://cryo.met.no/').href;
  const r = await fetch(url);
  const b = Buffer.from(await r.arrayBuffer());
  console.log(`\n== ${r.status} ${r.headers.get('content-type')} ${b.length} bytes ${r.headers.get('last-modified')} ${url}`);
  if (/zip/i.test(u)) { writeFileSync('/tmp/ice.zip', b); console.log(execSync('cd /tmp && unzip -o ice.zip && ls -la /tmp/*.shp /tmp/*.dbf /tmp/*.prj 2>/dev/null; cat /tmp/*.prj; python3 -c "import sys; d=open(sorted(__import__(\'glob\').glob(\'/tmp/*.dbf\'))[0],\'rb\').read(); n=int.from_bytes(d[4:8],\'little\'); h=int.from_bytes(d[8:10],\'little\'); print(\'records\',n); f=[d[i:i+11].split(b\'\\0\')[0].decode() for i in range(32,h-1,32)]; print(\'fields\',f)"', { encoding: 'utf8' })); }
}
