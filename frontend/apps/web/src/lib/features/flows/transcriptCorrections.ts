/**
 * Non-destructive transcript corrections, applied as a derived overlay on the
 * structured transcript lines (the same shape `applySpeakerNames` overlays).
 *
 * A correction is a char-range replacement anchored to the RAW segment text
 * the transcription step stored. The raw text is never rewritten, so every
 * corrected line can show what it was corrected from and be reverted.
 */

import type { TranscriptSegment } from "$lib/features/flows/transcriptSegments";

/** Wire shape of one stored correction (matches the backend API). */
export type CorrectionOccurrence = {
  segment_index: number;
  char_start: number;
  char_end: number;
  original: string;
  corrected: string;
};

export type AppliedCorrections = {
  segments: TranscriptSegment[];
  /** Raw (pre-correction) text per corrected segment index, for "corrected from". */
  correctedFrom: ReadonlyMap<number, string>;
  /** Occurrences whose anchor no longer matched; never applied approximately. */
  skipped: number;
};

/** Apply occurrences right-to-left per line so earlier offsets stay valid. */
export function applyTextCorrections(
  segments: readonly TranscriptSegment[],
  occurrences: readonly CorrectionOccurrence[]
): AppliedCorrections {
  if (occurrences.length === 0) {
    return { segments: [...segments], correctedFrom: new Map(), skipped: 0 };
  }
  const bySegment = new Map<number, CorrectionOccurrence[]>();
  let skipped = 0;
  for (const occurrence of occurrences) {
    if (occurrence.segment_index < 0 || occurrence.segment_index >= segments.length) {
      skipped += 1;
      continue;
    }
    const list = bySegment.get(occurrence.segment_index) ?? [];
    list.push(occurrence);
    bySegment.set(occurrence.segment_index, list);
  }
  const correctedFrom = new Map<number, string>();
  const result = segments.map((segment) => {
    const list = bySegment.get(segment.index);
    if (!list) return segment;
    let text = segment.text;
    let applied = false;
    const applicable = list.filter(
      (occurrence) =>
        occurrence.char_start >= 0 &&
        occurrence.char_end <= segment.text.length &&
        occurrence.char_start < occurrence.char_end &&
        segment.text.slice(occurrence.char_start, occurrence.char_end) === occurrence.original
    );
    skipped += list.length - applicable.length;
    for (const occurrence of [...applicable].sort((a, b) => b.char_start - a.char_start)) {
      text =
        text.slice(0, occurrence.char_start) +
        occurrence.corrected +
        text.slice(occurrence.char_end);
      applied = true;
    }
    if (!applied) return segment;
    correctedFrom.set(segment.index, segment.text);
    return { ...segment, text };
  });
  return { segments: result, correctedFrom, skipped };
}

export type LineEditDiff = {
  /** Minimal replacement in RAW-text space, or null when nothing changed. */
  occurrence: Omit<CorrectionOccurrence, "segment_index"> | null;
  /**
   * The changed region expanded to whole-token boundaries, when the change is
   * token-shaped (1-3 whole words replaced by non-empty text). This is what
   * seeds the "same correction elsewhere" search.
   */
  tokenShaped: { originalText: string; correctedText: string } | null;
};

const MAX_SUGGESTION_TOKENS = 3;

/** Minimal diff of one line edit: common prefix/suffix trim over the raw text. */
export function diffLineEdit(original: string, edited: string): LineEditDiff {
  if (original === edited) return { occurrence: null, tokenShaped: null };
  let start = 0;
  const maxStart = Math.min(original.length, edited.length);
  while (start < maxStart && original[start] === edited[start]) start += 1;
  let endOriginal = original.length;
  let endEdited = edited.length;
  while (
    endOriginal > start &&
    endEdited > start &&
    original[endOriginal - 1] === edited[endEdited - 1]
  ) {
    endOriginal -= 1;
    endEdited -= 1;
  }
  const occurrence = {
    char_start: start,
    char_end: endOriginal,
    original: original.slice(start, endOriginal),
    corrected: edited.slice(start, endEdited)
  };
  return { occurrence, tokenShaped: tokenShapedRegion(original, edited, occurrence) };
}

function tokenShapedRegion(
  original: string,
  edited: string,
  occurrence: Omit<CorrectionOccurrence, "segment_index">
): { originalText: string; correctedText: string } | null {
  const words = splitWords(original);
  // Closed-interval overlap so boundary contact counts: removing the space in
  // "Anna Lisa" must pull in both neighbouring tokens.
  const touched = words.filter(
    (word) =>
      word.offset <= occurrence.char_end && word.offset + word.word.length >= occurrence.char_start
  );
  if (touched.length === 0 || touched.length > MAX_SUGGESTION_TOKENS) return null;
  const lastTouched = touched[touched.length - 1];
  // Clamp so the region always contains the changed span; otherwise the
  // prefix/suffix mapping onto the edited string below would not hold.
  const regionStart = Math.min(touched[0].offset, occurrence.char_start);
  const regionEnd = Math.max(lastTouched.offset + lastTouched.word.length, occurrence.char_end);
  // The prefix [0, char_start) and suffix [char_end, …) are identical in both
  // strings, so expanding into them maps one-to-one onto the edited string.
  const shift = edited.length - original.length;
  const correctedText = edited.slice(regionStart, regionEnd + shift);
  if (correctedText.trim().length === 0) return null;
  if (/\s/.test(correctedText.trim()) && splitWords(correctedText).length > MAX_SUGGESTION_TOKENS) {
    return null;
  }
  return { originalText: original.slice(regionStart, regionEnd), correctedText };
}

export type WordSpan = { word: string; offset: number };

// A word is a run of letters/digits (Unicode-aware); surrounding punctuation
// stays out of the span so "sugary," matches the token "sugary". Never use
// ASCII \b here: names like "Çagri" have non-ASCII boundaries.
const WORD_RE = /[\p{L}\p{N}][\p{L}\p{N}'’-]*/gu;

export function splitWords(text: string): WordSpan[] {
  const words: WordSpan[] = [];
  for (const match of text.matchAll(WORD_RE)) {
    words.push({ word: match[0], offset: match.index ?? 0 });
  }
  return words;
}

function normalizeToken(token: string): string {
  return token.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "");
}

/** Levenshtein distance with early exit above `limit`. */
export function boundedEditDistance(a: string, b: string, limit: number): number {
  if (Math.abs(a.length - b.length) > limit) return limit + 1;
  if (a === b) return 0;
  let previous = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i += 1) {
    const current = [i];
    let rowMin = i;
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      const value = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost);
      current.push(value);
      if (value < rowMin) rowMin = value;
    }
    if (rowMin > limit) return limit + 1;
    previous = current;
  }
  return previous[b.length];
}

export type OccurrenceCandidate = {
  segmentIndex: number;
  charStart: number;
  charEnd: number;
  matchedText: string;
  kind: "exact" | "fuzzy";
};

const FUZZY_DISTANCE_LIMIT = 2;
export const MAX_SUGGESTION_CANDIDATES = 50;

/**
 * Other places the corrected text likely appears: exact whole-token matches
 * (case-insensitive) plus tokens within edit distance 2 of the normalized
 * form, to catch different manglings of the same name. Multi-word originals
 * match joined consecutive tokens. Matching is whole-token only — a token
 * that merely contains the text ("Chagrin" for "Chagri") is matched as a
 * fuzzy candidate at best, never replaced inside the token.
 */
export function findOccurrences(
  segments: readonly TranscriptSegment[],
  originalText: string,
  exclude: { segmentIndex: number; charStart: number } | null
): OccurrenceCandidate[] {
  const targetWords = splitWords(originalText).map((span) => span.word);
  if (targetWords.length === 0) return [];
  const targetLower = targetWords.map((word) => word.toLowerCase());
  const targetNormalized = normalizeToken(targetWords.join(" "));
  const candidates: OccurrenceCandidate[] = [];
  for (const segment of segments) {
    const words = splitWords(segment.text);
    for (let i = 0; i + targetWords.length <= words.length; i += 1) {
      const window = words.slice(i, i + targetWords.length);
      const charStart = window[0].offset;
      const last = window[window.length - 1];
      const charEnd = last.offset + last.word.length;
      if (
        exclude &&
        segment.index === exclude.segmentIndex &&
        charStart <= exclude.charStart &&
        exclude.charStart < charEnd
      ) {
        continue;
      }
      const matchedText = segment.text.slice(charStart, charEnd);
      let kind: "exact" | "fuzzy" | null = null;
      if (window.every((span, j) => span.word.toLowerCase() === targetLower[j])) {
        kind = "exact";
      } else if (
        boundedEditDistance(
          normalizeToken(window.map((span) => span.word).join(" ")),
          targetNormalized,
          FUZZY_DISTANCE_LIMIT
        ) <= FUZZY_DISTANCE_LIMIT
      ) {
        kind = "fuzzy";
      }
      if (kind) {
        candidates.push({ segmentIndex: segment.index, charStart, charEnd, matchedText, kind });
        if (candidates.length >= MAX_SUGGESTION_CANDIDATES) return candidates;
      }
    }
  }
  return candidates;
}

/** Carry the matched text's casing over to the replacement ("SUGARY" → "ÇAGRI"). */
export function applyCasingPattern(matchedText: string, replacement: string): string {
  if (matchedText === matchedText.toUpperCase() && /\p{L}/u.test(matchedText)) {
    return replacement.toUpperCase();
  }
  const first = matchedText.match(/\p{L}/u)?.[0];
  if (first && first === first.toUpperCase()) {
    return replacement.charAt(0).toUpperCase() + replacement.slice(1);
  }
  return replacement;
}

/** Canonical order so saves and dirty checks are stable. */
export function sortOccurrences(
  occurrences: readonly CorrectionOccurrence[]
): CorrectionOccurrence[] {
  return [...occurrences].sort(
    (a, b) => a.segment_index - b.segment_index || a.char_start - b.char_start
  );
}
