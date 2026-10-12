// Temporary: run the collector and summarise what it wrote.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
console.log(execFileSync('node', ['scripts/fetch-waves.mjs', '/tmp/w.json'], { encoding: 'utf8' }).split('\n').filter((l) => !l.startsWith('  ')).join('\n'));
const raw = readFileSync('/tmp/w.json', 'utf8'), j = JSON.parse(raw);
console.log('bytes', raw.length);
for (const s of j.stations) console.log(JSON.stringify({ ...s, hist: s.hist && [s.hist.length, s.hist[0], s.hist.at(-1)] }));
