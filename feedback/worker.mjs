/* Feedback from the chart app's menu, emailed to Matt: POST /api/feedback on
   northsea.surf and staging.northsea.surf (wrangler.toml's routes), JSON
   { text, website, lang, surface, v }. Sent with Email Routing's send_email
   binding (MAIL), from FROM to FEEDBACK_TO, a verified destination address
   on the account, set as a secret so it isn't in the repo (feedback.yml).

   Only from the app's own pages, only text up to 2000 characters, and
   anything that fills in the hidden website field (a bot) is thanked and
   dropped. */
import { EmailMessage } from 'cloudflare:email';
import { feedbackMail } from './mail.mjs';

const HOSTS = ['northsea.surf', 'staging.northsea.surf'];
const MAX = 2000;
const reply = (status) => new Response(null, { status });

export default {
  async fetch(req, env) {
    if (req.method !== 'POST') return reply(405);
    let host = '';
    try { host = new URL(req.headers.get('Origin')).hostname; } catch {}
    if (!HOSTS.includes(host)) return reply(403);
    let body;
    try { body = await req.json(); } catch { return reply(400); }
    const text = typeof body.text === 'string' ? body.text.trim() : '';
    if (!text || text.length > MAX) return reply(400);
    if (body.website) return reply(204);
    const clip = (v) => (typeof v === 'string' ? v.slice(0, 40).replace(/[^\w .:+-]/g, '') : '');
    const raw = feedbackMail({
      from: env.FROM, to: env.FEEDBACK_TO, text, id: crypto.randomUUID(), date: new Date(),
      meta: { site: host, language: clip(body.lang), open: clip(body.surface), version: clip(body.v) }
    });
    try { await env.MAIL.send(new EmailMessage(env.FROM, env.FEEDBACK_TO, raw)); } catch { return reply(502); }
    return reply(204);
  }
};
