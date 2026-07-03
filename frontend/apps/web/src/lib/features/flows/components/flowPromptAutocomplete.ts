/**
 * Cursor-position detection for the prompt editor's autocomplete triggers.
 * Pure string math, so the trigger rules can be tested without a DOM.
 */

/**
 * Index of the `{{` that opens an unclosed variable token at the cursor, or null
 * when the cursor is not inside an open `{{ … }}`.
 */
export function findOpenTokenStart(text: string, cursorIndex: number): number | null {
  const beforeCursor = text.slice(0, cursorIndex);
  const openIndex = beforeCursor.lastIndexOf("{{");
  if (openIndex < 0) return null;
  const closingIndex = beforeCursor.lastIndexOf("}}");
  if (closingIndex > openIndex) return null;
  return openIndex;
}

/**
 * Index of an `@` that starts an autocomplete trigger at the cursor, or null. An
 * `@` only triggers at the start of a word (preceded by whitespace or an opening
 * bracket), only while no space follows it, and never inside an open `{{ … }}`.
 */
export function findAtTriggerStart(text: string, cursor: number): number | null {
  if (findOpenTokenStart(text, cursor) !== null) return null;
  const beforeCursor = text.slice(0, cursor);
  const atIndex = beforeCursor.lastIndexOf("@");
  if (atIndex < 0) return null;
  if (atIndex > 0 && !/[\s([{]/.test(beforeCursor[atIndex - 1])) return null;
  if (beforeCursor.slice(atIndex + 1).includes(" ")) return null;
  return atIndex;
}
