/**
 * `text` cut into the parts that match `query` and the parts that do not, in
 * order, so a renderer can wrap the matches. Case-insensitive, every
 * occurrence; one segment with `match: false` when there is no query.
 */
export function splitMatches(text: string, query: string): { text: string; match: boolean }[] {
  if (!query || !text) return [{ text, match: false }];
  const segments: { text: string; match: boolean }[] = [];
  const lower = text.toLowerCase();
  let from = 0;
  for (;;) {
    const at = lower.indexOf(query, from);
    if (at === -1) break;
    if (at > from) segments.push({ text: text.slice(from, at), match: false });
    segments.push({ text: text.slice(at, at + query.length), match: true });
    from = at + query.length;
  }
  if (from < text.length) segments.push({ text: text.slice(from), match: false });
  return segments;
}
