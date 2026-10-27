// Decodes a frame with the app's own decode() (cut from app.js as it stands),
// for test_frames.py: node tests/decode_frame.cjs FRAME.bin.gz P S
// prints {p, u, v, h, t} as plain arrays.
const fs = require('fs'), path = require('path'), zlib = require('zlib');

const src = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
const start = src.indexOf('function decode(');
if (start < 0) throw new Error('no decode() in app.js');
let depth = 0, end = src.indexOf('{', start);
for (; end < src.length; end++) {
  if (src[end] === '{') depth++;
  else if (src[end] === '}' && --depth === 0) break;
}
const decode = new Function(`${src.slice(start, end + 1)}; return decode;`)();

const [file, P, S] = process.argv.slice(2);
const d = decode(new Uint8Array(zlib.gunzipSync(fs.readFileSync(file))), +P, +S);
process.stdout.write(JSON.stringify(Object.fromEntries(Object.entries(d).map(([k, a]) => [k, Array.from(a)]))));
