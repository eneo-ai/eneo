/**
 * Speaker turns: the display unit of the transcript view.
 *
 * A turn groups consecutive parts that belong to the same effective speaker,
 * across segment boundaries, so the reviewer reads a conversation instead of
 * raw ASR fragments. The storage unit stays the segment: every part keeps its
 * segment anchor (raw and display offsets), so seeking, editing, reverting,
 * and selection mapping never lose the anchor the backend needs.
 *
 * Everything here is pure and derived; nothing mutates segments or overlays.
 */

import type { CorrectionOccurrence } from "$lib/features/flows/transcriptCorrections";
import {
  applicableOccurrences,
  computeSegmentDetails,
  type SegmentDetails,
  type SpeakerEdit
} from "$lib/features/flows/transcriptRuns";
import type { TranscriptSegment } from "$lib/features/flows/transcriptSegments";

/** One segment-anchored slice of a turn's text. */
export type TurnPart = {
  segmentIndex: number;
  fileIndex: number;
  /** Seconds from the start of the part's file (the seek target). */
  start: number;
  /** Display-space text (corrections applied). */
  text: string;
  /** Raw-space span within the segment. */
  rawStart: number;
  rawEnd: number;
  /** Display-space span within the segment's corrected text. */
  displayStart: number;
  displayEnd: number;
  /** True when a speaker edit moved this part here. */
  overridden: boolean;
  /** Corrected sub-ranges, relative to this part's own text. */
  correctedRanges: { start: number; end: number }[];
};

export type TranscriptTurn = {
  /** Stable ordinal for keying. */
  index: number;
  /** Effective raw speaker label, or null for an unlabelled transcript. */
  speaker: string | null;
  fileIndex: number;
  /** Seconds: the first part's start. */
  start: number;
  parts: TurnPart[];
};

/** Display-space ranges the corrections rewrote, per raw line. */
export function correctedDisplayRanges(
  rawText: string,
  occurrences: readonly CorrectionOccurrence[]
): { start: number; end: number }[] {
  const ranges: { start: number; end: number }[] = [];
  let delta = 0;
  for (const occurrence of applicableOccurrences(rawText, occurrences)) {
    const start = occurrence.char_start + delta;
    const end = start + occurrence.corrected.length;
    // A pure deletion leaves no text to mark; the turn's revert still covers it.
    if (end > start) ranges.push({ start, end });
    delta += occurrence.corrected.length - (occurrence.char_end - occurrence.char_start);
  }
  return ranges;
}

/**
 * Group segments into speaker turns. Consecutive runs with the same effective
 * speaker merge across segments; a file boundary always breaks the turn.
 */
export function computeTurns(
  segments: readonly TranscriptSegment[],
  occurrences: readonly CorrectionOccurrence[],
  speakerEdits: readonly SpeakerEdit[],
  details?: Map<number, SegmentDetails>
): TranscriptTurn[] {
  const bySegment = details ?? computeSegmentDetails(segments, occurrences, speakerEdits);
  const occurrencesBySegment = new Map<number, CorrectionOccurrence[]>();
  for (const occurrence of occurrences) {
    const list = occurrencesBySegment.get(occurrence.segment_index) ?? [];
    list.push(occurrence);
    occurrencesBySegment.set(occurrence.segment_index, list);
  }
  const turns: TranscriptTurn[] = [];
  let current: TranscriptTurn | null = null;
  for (const segment of segments) {
    const detail = bySegment.get(segment.index);
    if (!detail) continue;
    const segmentRanges = correctedDisplayRanges(
      segment.text,
      occurrencesBySegment.get(segment.index) ?? []
    );
    for (const run of detail.runs) {
      const effective = run.speaker ?? segment.speaker;
      if (!current || current.speaker !== effective || current.fileIndex !== segment.fileIndex) {
        current = {
          index: turns.length,
          speaker: effective,
          fileIndex: segment.fileIndex,
          start: segment.start,
          parts: []
        };
        turns.push(current);
      }
      const correctedRanges = segmentRanges
        .map((range) => ({
          start: Math.max(range.start, run.displayStart) - run.displayStart,
          end: Math.min(range.end, run.displayEnd) - run.displayStart
        }))
        .filter((range) => range.start < range.end);
      current.parts.push({
        segmentIndex: segment.index,
        fileIndex: segment.fileIndex,
        start: segment.start,
        text: run.text,
        rawStart: run.rawStart,
        rawEnd: run.rawEnd,
        displayStart: run.displayStart,
        displayEnd: run.displayEnd,
        overridden: run.overridden,
        correctedRanges
      });
    }
  }
  return turns;
}

/** The text a whole-turn editor shows: part texts joined by single spaces. */
export function turnEditableText(turn: TranscriptTurn): string {
  return turn.parts.map((part) => part.text).join(" ");
}

export type TurnPartEdit = {
  segmentIndex: number;
  /** The segment's full new display text (this part's slice replaced). */
  newSegmentText: string;
};

/**
 * Split a whole-turn edit back onto the underlying segments.
 *
 * The edit is reduced to one changed window (common prefix/suffix trim in the
 * joined text). A window inside one part changes only that part; a window
 * crossing part boundaries assigns the replacement to the first overlapped
 * part, which keeps the concatenation exact while attribution inside the turn
 * (invisible to the reader) shifts at most one seam.
 */
export function splitTurnEdit(
  turn: TranscriptTurn,
  editedText: string,
  segmentDisplayText: (segmentIndex: number) => string
): TurnPartEdit[] {
  const original = turnEditableText(turn);
  if (original === editedText) return [];
  let windowStart = 0;
  const maxStart = Math.min(original.length, editedText.length);
  while (windowStart < maxStart && original[windowStart] === editedText[windowStart]) {
    windowStart += 1;
  }
  let windowEndOriginal = original.length;
  let windowEndEdited = editedText.length;
  while (
    windowEndOriginal > windowStart &&
    windowEndEdited > windowStart &&
    original[windowEndOriginal - 1] === editedText[windowEndEdited - 1]
  ) {
    windowEndOriginal -= 1;
    windowEndEdited -= 1;
  }
  const delta = windowEndEdited - windowEndOriginal;
  const mapBoundary = (boundary: number): number => {
    if (boundary <= windowStart) return boundary;
    if (boundary >= windowEndOriginal) return boundary + delta;
    // Inside the changed window: the first overlapped part absorbs it.
    return windowEndEdited;
  };

  const edits: TurnPartEdit[] = [];
  let originalPos = 0;
  let previousMappedEnd = 0;
  for (let index = 0; index < turn.parts.length; index += 1) {
    const part = turn.parts[index];
    const originalStart = originalPos;
    const originalEnd = originalStart + part.text.length;
    const mappedStart =
      index === 0
        ? 0
        : Math.min(Math.max(mapBoundary(originalStart), previousMappedEnd), editedText.length);
    const mappedEnd =
      index === turn.parts.length - 1
        ? editedText.length
        : Math.min(Math.max(mapBoundary(originalEnd), mappedStart), editedText.length);
    previousMappedEnd = mappedEnd;
    const newPartText = editedText.slice(mappedStart, mappedEnd);
    if (newPartText !== part.text) {
      const segmentText = segmentDisplayText(part.segmentIndex);
      edits.push({
        segmentIndex: part.segmentIndex,
        newSegmentText:
          segmentText.slice(0, part.displayStart) + newPartText + segmentText.slice(part.displayEnd)
      });
    }
    // Skip the joining separator between parts.
    originalPos = originalEnd + 1;
    previousMappedEnd = Math.min(previousMappedEnd + 1, editedText.length);
  }
  return edits;
}

/**
 * Map a selection in the (pristine) turn editor, expressed as offsets into
 * `turnEditableText`, onto per-segment display spans for reassignment.
 */
export function turnSelectionToDisplaySpans(
  turn: TranscriptTurn,
  joinedStart: number,
  joinedEnd: number
): { segmentIndex: number; displayStart: number; displayEnd: number }[] {
  const spans: { segmentIndex: number; displayStart: number; displayEnd: number }[] = [];
  let originalPos = 0;
  for (const part of turn.parts) {
    const partStart = originalPos;
    const partEnd = partStart + part.text.length;
    const overlapStart = Math.max(joinedStart, partStart);
    const overlapEnd = Math.min(joinedEnd, partEnd);
    if (overlapStart < overlapEnd) {
      spans.push({
        segmentIndex: part.segmentIndex,
        displayStart: part.displayStart + (overlapStart - partStart),
        displayEnd: part.displayStart + (overlapEnd - partStart)
      });
    }
    originalPos = partEnd + 1;
  }
  return spans;
}
