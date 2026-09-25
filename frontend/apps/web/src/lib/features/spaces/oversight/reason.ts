import { m } from "$lib/paraglide/messages";

/**
 * The API's rule for a written reason, mirrored from backend
 * `audit/application/free_text.py`, which is the reference. Lengths count
 * code points, not UTF-16 units.
 */
export const REASON_MIN_LENGTH = 10;
export const REASON_MAX_LENGTH = 500;

// Unicode White_Space. JS `\s` differs: it has U+FEFF and lacks U+0085.
const WHITESPACE =
  "\\t\\n\\v\\f\\r \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const WHITESPACE_RUN = new RegExp(`[${WHITESPACE}]+`, "gu");
const IS_WHITESPACE = new RegExp(`^[${WHITESPACE}]$`, "u");
// Invisible code points: format characters, lone surrogates, default ignorables
// (Hangul fillers, variation selectors, tags) and the blank Braille pattern.
const INVISIBLE = /[\p{Cf}\p{Cs}\p{Default_Ignorable_Code_Point}\u2800]/u;
const MARK = /^\p{M}$/u;

function isRemoved(char: string): boolean {
  if (INVISIBLE.test(char)) return true;
  return /^\p{Cc}$/u.test(char) && !IS_WHITESPACE.test(char);
}

/**
 * The reason as the API stores it: invisible and control characters removed,
 * composed to NFC, every whitespace run collapsed to one space, trimmed.
 */
export function normalizeReason(value: string): string {
  const kept = [...value].filter((char) => !isRemoved(char)).join("");
  return kept
    .normalize("NFC")
    .replace(WHITESPACE_RUN, " ")
    .replace(/^ +| +$/g, "");
}

/** Characters that show: neither whitespace nor a combining mark. */
export function visibleLength(text: string): number {
  return [...text].filter((char) => !IS_WHITESPACE.test(char) && !MARK.test(char)).length;
}

/** The stored length the counter shows, in code points. */
export function reasonLength(value: string): number {
  return [...normalizeReason(value)].length;
}

/** The message to show under a reason field when submitting `value`, or null when it is valid. */
export function reasonError(value: string): string | null {
  const normalized = normalizeReason(value);
  if (visibleLength(normalized) < REASON_MIN_LENGTH) {
    return m.oversight_reason_too_short({ min: REASON_MIN_LENGTH });
  }
  if ([...normalized].length > REASON_MAX_LENGTH) {
    return m.oversight_reason_too_long({ max: REASON_MAX_LENGTH });
  }
  return null;
}
