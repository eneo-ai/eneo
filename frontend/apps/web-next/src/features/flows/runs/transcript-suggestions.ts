import type { TranscriptSegment } from "./transcript";
import { diffLineEdit, type CorrectionSet, type Occurrence } from "./transcript-corrections";

/**
 * "Same correction elsewhere": when the reviewer corrects a word or a name
 * (up to three words), the other places the transcript likely says the
 * same are offered for the same correction. Exact matches (any case) and
 * close spellings (within two edits, accents ignored) of whole words; a word
 * that only contains the text is never changed inside. Nothing is applied
 * without the reviewer choosing it. Pure; offsets are UTF-16 offsets of the
 * lines' raw text.
 */

export type SuggestionKind = "exact" | "similar";

export type Candidate = {
  segmentIndex: number;
  charStart: number;
  charEnd: number;
  matched: string;
  kind: SuggestionKind;
};

export type Suggestions = {
  /** The words as they stood, and what they were corrected to. */
  original: string;
  corrected: string;
  candidates: Candidate[];
};

const MAX_WORDS = 3;
const SIMILAR_DISTANCE = 2;
export const MAX_CANDIDATES = 50;

// A word is a run of letters or digits (any script); punctuation around it
// stays out, so "Çagri," matches "Çagri". Never \b: it is ASCII only.
const WORD = /[\p{L}\p{N}][\p{L}\p{N}'’-]*/gu;

type Word = { word: string; offset: number };

export function splitWords(text: string): Word[] {
  return [...text.matchAll(WORD)].map((match) => ({ word: match[0], offset: match.index }));
}

function normalized(text: string): string {
  return text.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "");
}

/** Levenshtein distance, giving up above `limit`. */
export function editDistance(a: string, b: string, limit: number): number {
  if (Math.abs(a.length - b.length) > limit) return limit + 1;
  if (a === b) return 0;
  let previous = Array.from({ length: b.length + 1 }, (_, index) => index);
  for (let i = 1; i <= a.length; i += 1) {
    const current = [i];
    let rowMin = i;
    for (let j = 1; j <= b.length; j += 1) {
      const value = Math.min(
        previous[j]! + 1,
        current[j - 1]! + 1,
        previous[j - 1]! + (a[i - 1] === b[j - 1] ? 0 : 1)
      );
      current.push(value);
      rowMin = Math.min(rowMin, value);
    }
    if (rowMin > limit) return limit + 1;
    previous = current;
  }
  return previous[b.length]!;
}

/**
 * The words an edit of a line touched, widened to whole words, and what
 * they became: null unless one to three whole words were replaced by text.
 */
export function changedWords(
  raw: string,
  edited: string
): { original: string; corrected: string; start: number } | null {
  const change = diffLineEdit(raw, edited);
  if (!change) return null;
  // Touching counts: removing the space in "Anna Lisa" takes both words.
  const touched = splitWords(raw).filter(
    (word) => word.offset <= change.char_end && word.offset + word.word.length >= change.char_start
  );
  if (touched.length === 0 || touched.length > MAX_WORDS) return null;
  const last = touched.at(-1)!;
  const start = Math.min(touched[0]!.offset, change.char_start);
  const end = Math.max(last.offset + last.word.length, change.char_end);
  // What lies outside the change is the same in both texts.
  const corrected = edited.slice(start, end + edited.length - raw.length);
  const after = splitWords(corrected).map((word) => word.word);
  if (!corrected.trim() || after.length > MAX_WORDS) return null;
  const original = raw.slice(start, end);
  // Only punctuation changed: no word to look for elsewhere.
  if (
    after.join(" ") ===
    splitWords(original)
      .map((word) => word.word)
      .join(" ")
  )
    return null;
  return { original, corrected, start };
}

/**
 * Other places `original` (whole words) likely stands: exact matches first
 * by line, then close spellings; the place the reviewer edited is left out.
 */
export function findOccurrences(
  segments: readonly Pick<TranscriptSegment, "index" | "text">[],
  original: string,
  exclude: { segmentIndex: number; charStart: number } | null
): Candidate[] {
  const target = splitWords(original).map((word) => word.word);
  if (target.length === 0) return [];
  const lower = target.map((word) => word.toLowerCase());
  const plain = normalized(target.join(" "));
  const found: Candidate[] = [];
  for (const segment of segments) {
    const words = splitWords(segment.text);
    for (let at = 0; at + target.length <= words.length; at += 1) {
      const window = words.slice(at, at + target.length);
      const charStart = window[0]!.offset;
      const last = window.at(-1)!;
      const charEnd = last.offset + last.word.length;
      if (
        exclude &&
        segment.index === exclude.segmentIndex &&
        charStart <= exclude.charStart &&
        exclude.charStart < charEnd
      ) {
        continue;
      }
      const kind: SuggestionKind | null = window.every(
        (word, index) => word.word.toLowerCase() === lower[index]
      )
        ? "exact"
        : editDistance(
              normalized(window.map((word) => word.word).join(" ")),
              plain,
              SIMILAR_DISTANCE
            ) <= SIMILAR_DISTANCE
          ? "similar"
          : null;
      if (!kind) continue;
      found.push({
        segmentIndex: segment.index,
        charStart,
        charEnd,
        matched: segment.text.slice(charStart, charEnd),
        kind
      });
      if (found.length >= MAX_CANDIDATES) return found;
    }
  }
  return found;
}

/**
 * The match's casing carried over to the replacement: all capitals stay all
 * capitals, a capital first letter stays one; otherwise as the reviewer typed it.
 */
export function withCasingOf(matched: string, replacement: string): string {
  if (matched === matched.toUpperCase() && /\p{L}/u.test(matched)) {
    return replacement.toUpperCase();
  }
  const first = matched.match(/\p{L}/u)?.[0];
  if (first && first === first.toUpperCase()) {
    return replacement.charAt(0).toUpperCase() + replacement.slice(1);
  }
  return replacement;
}

function overlaps(candidate: Candidate, occurrences: readonly Occurrence[]): boolean {
  return occurrences.some(
    (occurrence) =>
      occurrence.segment_index === candidate.segmentIndex &&
      occurrence.char_start < candidate.charEnd &&
      candidate.charStart < occurrence.char_end
  );
}

/**
 * The places to offer after line `segment` was edited to `edited` (the set
 * `next` already holds that edit), or null when there are none: the edit
 * must replace whole words, and a place another correction already covers
 * is left out.
 */
export function suggestionsFor(
  next: CorrectionSet,
  segment: Pick<TranscriptSegment, "index" | "text">,
  edited: string,
  segments: readonly Pick<TranscriptSegment, "index" | "text">[]
): Suggestions | null {
  const change = changedWords(segment.text, edited);
  if (!change) return null;
  const candidates = findOccurrences(segments, change.original, {
    segmentIndex: segment.index,
    charStart: change.start
  }).filter((candidate) => !overlaps(candidate, next.occurrences));
  return candidates.length > 0
    ? { original: change.original, corrected: change.corrected, candidates }
    : null;
}

/** The set with the chosen places corrected too. */
export function withSuggestions(
  set: CorrectionSet,
  suggestions: Pick<Suggestions, "corrected">,
  chosen: readonly Candidate[]
): CorrectionSet {
  return {
    ...set,
    occurrences: [
      ...set.occurrences,
      ...chosen.map((candidate) => ({
        segment_index: candidate.segmentIndex,
        char_start: candidate.charStart,
        char_end: candidate.charEnd,
        original: candidate.matched,
        corrected: withCasingOf(candidate.matched, suggestions.corrected)
      }))
    ]
  };
}
