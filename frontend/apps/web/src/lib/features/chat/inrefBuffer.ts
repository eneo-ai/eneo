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
  const couldBeTag = tail.length <= TAG.length ? TAG.startsWith(tail) : tail.startsWith(TAG);
  if (!couldBeTag || tail.includes(">")) return [buffer, ""];
  return [buffer.slice(0, start), tail];
}
