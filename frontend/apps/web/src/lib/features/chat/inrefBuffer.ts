/*
    Copyright (c) 2026 Sundsvalls Kommun
*/

const TAG = "<inref";

/**
 * Splits streamed answer text into what can be shown now and a trailing
 * fragment that may still become an `<inref …/>` citation tag.
 *
 * Only the text from the last "<" onwards can be an unfinished tag, so
 * everything before it is safe to render, including earlier complete
 * citations. The previous check looked at the first "<" only, so a chunk
 * holding a complete citation followed by the start of another released the
 * unfinished tag as visible text.
 */
export function splitPendingInref(buffer: string): [ready: string, pending: string] {
  const start = buffer.lastIndexOf("<");
  if (start === -1) return [buffer, ""];
  const tail = buffer.slice(start);
  if (!couldBecomeTag(tail) || tail.includes(">")) return [buffer, ""];
  return [buffer.slice(0, start), tail];
}

/**
 * True while the fragment is a prefix of a citation tag. The renderer only
 * accepts `<inref` followed by whitespace or `/`, so `<inreference prose`
 * can never become a citation and is released at once instead of being
 * withheld until the next `>`.
 */
function couldBecomeTag(tail: string): boolean {
  if (tail.length <= TAG.length) return TAG.startsWith(tail);
  if (!tail.startsWith(TAG)) return false;
  return /^[\s/]/.test(tail.charAt(TAG.length));
}
