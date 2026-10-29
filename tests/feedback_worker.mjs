// Runs the feedback Worker (feedback/worker.mjs) under Node, for
// test_feedback.py: cloudflare:email stood in for by a class that keeps what
// it's given, and env.MAIL by one that records each message. Reads the
// requests to make as JSON on stdin; writes, for each, the status and the
// message sent (if any) as JSON on stdout.
import { register } from 'node:module';

register('data:text/javascript,' + encodeURIComponent(`
  export async function resolve(spec, ctx, next) {
    if (spec === 'cloudflare:email') return { url: 'data:text/javascript,' + encodeURIComponent(
      'export class EmailMessage { constructor(from, to, raw) { Object.assign(this, { from, to, raw }); } }'), shortCircuit: true };
    return next(spec, ctx);
  }`));
const { default: worker } = await import(new URL('../feedback/worker.mjs', import.meta.url));

let input = '';
for await (const chunk of process.stdin) input += chunk;
const out = [];
for (const r of JSON.parse(input)) {
  const sent = [];
  const env = { FROM: 'feedback@northsea.surf', FEEDBACK_TO: 'matt@example.com',
    MAIL: { send: async (m) => { if (r.mailFails) throw new Error('not verified'); sent.push(m); } } };
  const headers = { 'Content-Type': 'application/json', ...(r.origin ? { Origin: r.origin } : {}) };
  const req = new Request('https://northsea.surf/api/feedback', { method: r.method || 'POST', headers, body: r.method === 'GET' ? undefined : r.body });
  const res = await worker.fetch(req, env);
  out.push({ status: res.status, sent: sent.map(({ from, to, raw }) => ({ from, to, raw })) });
}
process.stdout.write(JSON.stringify(out));
