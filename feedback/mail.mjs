/* The feedback email itself, as the raw message Email Routing sends: plain
   text in UTF-8 (base64, so any language's letters arrive intact), with what
   the app said about where it was sent from beneath it. Apart from the
   Worker (worker.mjs) so it can be tested without Cloudflare. */

const b64 = (s) => {
  const bytes = new TextEncoder().encode(s);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/.{76}/g, '$&\r\n');
};

export function feedbackMail({ from, to, text, meta, id, date }) {
  const about = Object.entries(meta).filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join('\n');
  return [
    `From: North Sea Surf <${from}>`,
    `To: ${to}`,
    'Subject: North Sea Surf feedback',
    `Message-ID: <${id}@${from.split('@')[1]}>`,
    `Date: ${date.toUTCString()}`,
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=utf-8',
    'Content-Transfer-Encoding: base64',
    '',
    b64(`${text}\n\n--\n${about}\n`)
  ].join('\r\n');
}
