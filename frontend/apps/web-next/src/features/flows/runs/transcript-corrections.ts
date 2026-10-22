import type { Schema } from "@/lib/api/models";
import type { TranscriptCorrections, TranscriptSegment } from "./transcript";

/**
 * Editing a run's transcript corrections. A correction replaces a span of a
 * line's raw text, which is never rewritten, so every corrected line can show
 * what it was and be reverted. The core counts offsets in Unicode code
 * points and JavaScript strings in UTF-16 units: offsets are converted at the
 * wire, and everything here works on UTF-16 offsets. An anchor that no
 * longer matches its line is never applied approximately.
 *
 * The edit endpoint replaces the step's whole set (revision-fenced), so each
 * change is the saved set with one line changed.
 */

export type WireOccurrence = Schema<"TranscriptCorrectionOccurrencePublic">;
export type WireSpeakerEdit = Schema<"TranscriptSpeakerEditPublic">;
export type EditRequest = Schema<"FlowTranscriptCorrectionsEditRequest">;

/** A text correction in UTF-16 offsets of the line's raw text. */
export type Occurrence = {
  segment_index: number;
  char_start: number;
  char_end: number;
  original: string;
  corrected: string;
};

/** The corrections of one step as the editor works on them (UTF-16 offsets). */
export type CorrectionSet = {
  occurrences: Occurrence[];
  speakerEdits: WireSpeakerEdit[];
  names: Record<string, string | null>;
};

type RawLine = Pick<TranscriptSegment, "index" | "text">;

function rawTexts(segments: readonly RawLine[]): Map<number, string> {
  return new Map(segments.map((segment) => [segment.index, segment.text]));
}

/** A code-point offset as a UTF-16 offset in `text`. */
function fromCodePoints(text: string, offset: number): number {
  return Array.from(text).slice(0, offset).join("").length;
}

/** A UTF-16 offset as a code-point offset; refuses one that splits a code point. */
function toCodePoints(text: string, offset: number): number {
  if (
    offset > 0 &&
    offset < text.length &&
    /[\uD800-\uDBFF]/.test(text[offset - 1]!) &&
    /[\uDC00-\uDFFF]/.test(text[offset]!)
  ) {
    throw new Error("A transcript anchor splits a Unicode code point.");
  }
  return Array.from(text.slice(0, offset)).length;
}

function convert<
  T extends { segment_index: number; char_start?: number | null; char_end?: number | null }
>(
  entries: readonly T[],
  texts: Map<number, string>,
  convertOffset: (text: string, offset: number) => number
): T[] {
  return entries.map((entry) => {
    const text = texts.get(entry.segment_index);
    if (text === undefined) return { ...entry };
    const at = (value: number | null | undefined) =>
      value == null ? value : convertOffset(text, value);
    return { ...entry, char_start: at(entry.char_start), char_end: at(entry.char_end) };
  });
}

/** The saved corrections as the editor works on them. */
export function correctionSet(
  saved: Pick<TranscriptCorrections, "occurrences" | "speaker_edits" | "speaker_names"> | null,
  segments: readonly RawLine[]
): CorrectionSet {
  const texts = rawTexts(segments);
  return {
    occurrences: convert(saved?.occurrences ?? [], texts, fromCodePoints),
    speakerEdits: convert(saved?.speaker_edits ?? [], texts, fromCodePoints),
    names: { ...(saved?.speaker_names ?? {}) }
  };
}

/** The edit request that saves `set` over the saved corrections. */
export function editRequest(
  saved: Pick<TranscriptCorrections, "revision" | "segments_hash"> | null,
  set: CorrectionSet,
  segments: readonly RawLine[],
  sourceHash: string
): EditRequest {
  const texts = rawTexts(segments);
  return {
    expected_revision: saved?.revision ?? null,
    segments_hash: saved?.segments_hash ?? sourceHash,
    schema_version: 3,
    occurrences: convert(sortOccurrences(set.occurrences), texts, toCodePoints),
    speaker_edits: convert(set.speakerEdits, texts, toCodePoints),
    speaker_names: set.names
  };
}

/** Canonical order, so a save and a dirty check are stable. */
export function sortOccurrences(occurrences: readonly Occurrence[]): Occurrence[] {
  return [...occurrences].sort(
    (a, b) => a.segment_index - b.segment_index || a.char_start - b.char_start
  );
}

/** The occurrences that still match a line's raw text, in text order. */
export function applicableOccurrences(
  rawText: string,
  occurrences: readonly Occurrence[]
): Occurrence[] {
  return occurrences
    .filter(
      (occurrence) =>
        occurrence.char_start >= 0 &&
        occurrence.char_end <= rawText.length &&
        occurrence.char_start < occurrence.char_end &&
        rawText.slice(occurrence.char_start, occurrence.char_end) === occurrence.original
    )
    .sort((a, b) => a.char_start - b.char_start);
}

/** A line's text with its applicable corrections. */
export function correctedText(rawText: string, occurrences: readonly Occurrence[]): string {
  let text = rawText;
  for (const occurrence of [...applicableOccurrences(rawText, occurrences)].reverse()) {
    text =
      text.slice(0, occurrence.char_start) + occurrence.corrected + text.slice(occurrence.char_end);
  }
  return text;
}

/**
 * The smallest replacement that turns `raw` into `edited`: the common start
 * and end trimmed. A pure insertion takes one neighbouring character along,
 * since a correction must replace some text. Null when nothing changed, or
 * when the raw line is empty and there is nothing to anchor to.
 */
export function diffLineEdit(
  raw: string,
  edited: string
): Omit<Occurrence, "segment_index"> | null {
  if (raw === edited) return null;
  const rawPoints = Array.from(raw);
  const editedPoints = Array.from(edited);
  let start = 0;
  const maxStart = Math.min(rawPoints.length, editedPoints.length);
  while (start < maxStart && rawPoints[start] === editedPoints[start]) start += 1;
  let endRaw = rawPoints.length;
  let endEdited = editedPoints.length;
  while (
    endRaw > start &&
    endEdited > start &&
    rawPoints[endRaw - 1] === editedPoints[endEdited - 1]
  ) {
    endRaw -= 1;
    endEdited -= 1;
  }
  if (start === endRaw) {
    if (endRaw < rawPoints.length) {
      endRaw += 1;
      endEdited += 1;
    } else if (start > 0) {
      start -= 1;
    } else {
      return null;
    }
  }
  // Whole code points in the anchor, then UTF-16 offsets.
  const at = (points: string[], count: number) => points.slice(0, count).join("").length;
  const charStart = at(rawPoints, start);
  const charEnd = at(rawPoints, endRaw);
  const editedEnd = at(editedPoints, endEdited);
  return {
    char_start: charStart,
    char_end: charEnd,
    original: raw.slice(charStart, charEnd),
    corrected: edited.slice(charStart, editedEnd)
  };
}

/** The set with line `segment`'s text corrected to `edited` (its raw text: the corrections go). */
export function withLineText(set: CorrectionSet, segment: RawLine, edited: string): CorrectionSet {
  const others = set.occurrences.filter((occurrence) => occurrence.segment_index !== segment.index);
  const change = diffLineEdit(segment.text, edited);
  return {
    ...set,
    occurrences: change ? [...others, { segment_index: segment.index, ...change }] : others
  };
}

/** The set without line `segmentIndex`'s text corrections. */
export function withoutLineText(set: CorrectionSet, segmentIndex: number): CorrectionSet {
  return {
    ...set,
    occurrences: set.occurrences.filter((occurrence) => occurrence.segment_index !== segmentIndex)
  };
}
