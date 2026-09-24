import { m } from "$lib/paraglide/messages";

/** The API's bounds for a written reason (backend `audit/application/free_text.py`). */
export const REASON_MIN_LENGTH = 10;
export const REASON_MAX_LENGTH = 500;

// The API drops zero-width and directional marks, bidi embeddings and
// isolates, and control characters that are not whitespace, before counting.
const FORMAT_CONTROLS = /[\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069]/gu;
const CONTROLS = /(?!\s)\p{Cc}/gu;

/**
 * The reason as the API stores and counts it: one line, every whitespace run
 * collapsed to a single space, trimmed.
 */
export function normalizeReason(value: string): string {
  return value
    .normalize("NFC")
    .replace(FORMAT_CONTROLS, "")
    .replace(CONTROLS, "")
    .replace(/\s+/gu, " ")
    .trim();
}

/** The message to show under a reason field when submitting `value`, or null when it is valid. */
export function reasonError(value: string): string | null {
  return normalizeReason(value).length < REASON_MIN_LENGTH
    ? m.oversight_reason_too_short({ min: REASON_MIN_LENGTH })
    : null;
}
