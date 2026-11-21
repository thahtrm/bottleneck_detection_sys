const ISSUE_KEY = /^[A-Z][A-Z0-9]+-\d+$/;
const TOKEN = /<[^|>]*\|([^>]+)>|([A-Z][A-Z0-9]+-\d+)/g;

export function splitChatText(body) {
  const text = body || '';
  const parts = [];
  let last = 0;
  for (const match of text.matchAll(TOKEN)) {
    const start = match.index ?? 0;
    if (start > last) parts.push({ type: 'text', text: text.slice(last, start) });
    const label = match[1];
    const bare = match[2];
    if (label && ISSUE_KEY.test(label)) parts.push({ type: 'issue', key: label });
    else if (label) parts.push({ type: 'text', text: label });
    else if (bare) parts.push({ type: 'issue', key: bare });
    last = start + match[0].length;
  }
  if (last < text.length) parts.push({ type: 'text', text: text.slice(last) });
  if (parts.length === 0) parts.push({ type: 'text', text: '' });
  return parts;
}

export function pinChatToLatest(viewport) {
  if (!viewport) return;
  viewport.scrollTop = viewport.scrollHeight;
}
