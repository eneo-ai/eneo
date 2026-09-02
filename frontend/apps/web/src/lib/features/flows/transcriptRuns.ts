/**
 * Attribution runs for a transcript line: which speaker owns which part of a
 * segment once text corrections and speaker edits overlay the raw text.
 *
 * A speaker edit reassigns a whole segment (null span) or a raw-text span of
 * it to another raw label. Like text corrections, edits anchor to the RAW
 * segment text and are skipped when the anchor no longer matches — never
 * applied approximately.
 *
 * The offset mapping and run computation mirror the backend domain module
 * (`flows/domain/transcript_corrections.py`); the two must stay in lockstep.
 */

import type { CorrectionOccurrence } from "$lib/features/flows/transcriptCorrections";
import type { TranscriptSegment } from "$lib/features/flows/transcriptSegments";

/** Wire shape of one stored speaker edit (matches the backend API). */
export type SpeakerEdit = {
  segment_index: number;
  /** Inclusive raw-text offset, or null for a whole-segment reassignment. */
  char_start: number | null;
  /** Exclusive raw-text offset, or null for a whole-segment reassignment. */
  char_end: number | null;
  /** The exact raw text of the span, or null for a whole-segment edit. */
  original: string | null;
  /** The segment's stored label the edit anchors to. */
  original_speaker: string;
  /** The raw label the content is reassigned to. */
  speaker: string;
};

/** A requested reassignment before anchors are filled in from raw segments. */
export type SpeakerSpanInput = {
  segment_index: number;
  /** Raw-space span; null endpoints reassign the whole segment. */
  char_start: number | null;
  char_end: number | null;
  speaker: string;
};

export type OffsetBias = "start" | "end";

/** Piecewise raw<->display mapping derived from one segment's corrections. */
export type OffsetMap = {
  rawToDisplay(offset: number): number;
  displayToRaw(offset: number, bias: OffsetBias): number;
};

/** Anchor-verified occurrences for one raw line, sorted by offset. */
export function applicableOccurrences(
  rawText: string,
  occurrences: readonly CorrectionOccurrence[]
): CorrectionOccurrence[] {
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

function mapFromApplicable(applicable: readonly CorrectionOccurrence[]): OffsetMap {
  return {
    /** Monotone and total; an offset inside a replaced span clamps within it. */
    rawToDisplay(offset: number): number {
      let delta = 0;
      for (const occurrence of applicable) {
        if (occurrence.char_end <= offset) {
          delta += occurrence.corrected.length - (occurrence.char_end - occurrence.char_start);
        } else if (occurrence.char_start < offset) {
          const inSpan = Math.min(offset - occurrence.char_start, occurrence.corrected.length);
          return occurrence.char_start + delta + inSpan;
        } else {
          break;
        }
      }
      return offset + delta;
    },
    displayToRaw(offset: number, bias: OffsetBias): number {
      let delta = 0;
      for (const occurrence of applicable) {
        const displayStart = occurrence.char_start + delta;
        const displayEnd = displayStart + occurrence.corrected.length;
        if (offset <= displayStart) return offset - delta;
        if (offset < displayEnd) {
          // Inside a replaced span: snap to the raw span's edge.
          return bias === "start" ? occurrence.char_start : occurrence.char_end;
        }
        delta += occurrence.corrected.length - (occurrence.char_end - occurrence.char_start);
      }
      return offset - delta;
    }
  };
}

export function buildOffsetMap(
  rawText: string,
  occurrences: readonly CorrectionOccurrence[]
): OffsetMap {
  return mapFromApplicable(applicableOccurrences(rawText, occurrences));
}

/** One visually distinct part of a rendered transcript line. */
export type SegmentRun = {
  /** Effective raw label, or null when the segment's own speaker applies. */
  speaker: string | null;
  /** True when a speaker edit produced this run (drives reset + tooltip). */
  overridden: boolean;
  /** Display-space slice (text corrections applied). */
  text: string;
  /** Raw-space span — the identity a revert addresses. */
  rawStart: number;
  rawEnd: number;
  /** Display-space span — what DOM selection offsets resolve against. */
  displayStart: number;
  displayEnd: number;
};

function anchorsToSegment(
  edit: SpeakerEdit,
  rawText: string,
  segmentSpeaker: string | null
): boolean {
  if (segmentSpeaker === null || edit.original_speaker !== segmentSpeaker) return false;
  if (edit.char_start === null || edit.char_end === null) return edit.original === null;
  return (
    edit.char_start >= 0 &&
    edit.char_end <= rawText.length &&
    edit.char_start < edit.char_end &&
    rawText.slice(edit.char_start, edit.char_end) === edit.original
  );
}

/**
 * The attribution runs of one segment. No applicable edits yield exactly one
 * `speaker: null` run; a whole-segment edit yields one overridden run; span
 * edits split the line, with boundaries mapped into display space through the
 * segment's text corrections.
 */
export function computeSegmentRuns(
  rawText: string,
  segmentSpeaker: string | null,
  occurrences: readonly CorrectionOccurrence[],
  speakerEdits: readonly SpeakerEdit[]
): SegmentRun[] {
  const applicable = applicableOccurrences(rawText, occurrences);
  const map = mapFromApplicable(applicable);
  let displayText = rawText;
  for (const occurrence of [...applicable].sort((a, b) => b.char_start - a.char_start)) {
    displayText =
      displayText.slice(0, occurrence.char_start) +
      occurrence.corrected +
      displayText.slice(occurrence.char_end);
  }
  const baseRun: SegmentRun = {
    speaker: null,
    overridden: false,
    text: displayText,
    rawStart: 0,
    rawEnd: rawText.length,
    displayStart: 0,
    displayEnd: displayText.length
  };
  const anchored = speakerEdits.filter((edit) => anchorsToSegment(edit, rawText, segmentSpeaker));
  const whole = anchored.find((edit) => edit.char_start === null);
  if (whole) {
    return [{ ...baseRun, speaker: whole.speaker, overridden: true }];
  }
  const spans = anchored
    .filter((edit) => edit.char_start !== null)
    .sort((a, b) => (a.char_start ?? 0) - (b.char_start ?? 0));
  if (spans.length === 0) return [baseRun];

  const runs: SegmentRun[] = [];
  const push = (rawStart: number, rawEnd: number, speaker: string | null, overridden: boolean) => {
    const displayStart = map.rawToDisplay(rawStart);
    const displayEnd = map.rawToDisplay(rawEnd);
    if (displayStart >= displayEnd) return;
    runs.push({
      speaker,
      overridden,
      text: displayText.slice(displayStart, displayEnd),
      rawStart,
      rawEnd,
      displayStart,
      displayEnd
    });
  };
  let cursor = 0;
  for (const edit of spans) {
    const start = edit.char_start ?? 0;
    const end = edit.char_end ?? 0;
    // Overlapping stored spans can only mean corrupt storage; skip, never guess.
    if (start < cursor) continue;
    if (cursor < start) push(cursor, start, null, false);
    push(start, end, edit.speaker, true);
    cursor = end;
  }
  if (cursor < rawText.length) push(cursor, rawText.length, null, false);
  return runs.length > 0 ? runs : [baseRun];
}

/** Canonical order: by segment, whole-segment edits before spans by offset. */
export function sortSpeakerEdits(speakerEdits: readonly SpeakerEdit[]): SpeakerEdit[] {
  return [...speakerEdits].sort(
    (a, b) =>
      a.segment_index - b.segment_index ||
      (a.char_start === null ? -1 : a.char_start) - (b.char_start === null ? -1 : b.char_start)
  );
}

type RawRun = { start: number; end: number; speaker: string };

function overlayRun(runs: RawRun[], start: number, end: number, speaker: string): RawRun[] {
  if (start >= end) return runs;
  const next: RawRun[] = [];
  for (const run of runs) {
    if (run.end <= start || run.start >= end) {
      next.push(run);
      continue;
    }
    if (run.start < start) next.push({ start: run.start, end: start, speaker: run.speaker });
    if (run.end > end) next.push({ start: end, end: run.end, speaker: run.speaker });
  }
  next.push({ start, end, speaker });
  return next.sort((a, b) => a.start - b.start);
}

/**
 * Merge requested reassignments over the stored edits, last writer wins, and
 * re-serialize canonically: per segment the effective attribution is rebuilt
 * as raw-space runs, and only runs whose speaker differs from the stored one
 * become edits again — one whole-segment (null-span) edit when a single run
 * covers everything, span edits otherwise. Normalization guarantees the
 * backend invariants by construction: no overlaps, no whole+span conflicts,
 * no no-ops, and anchors (`original`, `original_speaker`) filled from the raw
 * segments.
 */
export function applySpeakerEditOverlay(
  existing: readonly SpeakerEdit[],
  incoming: readonly SpeakerSpanInput[],
  rawSegments: readonly TranscriptSegment[]
): SpeakerEdit[] {
  const touched = new Set<number>([
    ...existing.map((edit) => edit.segment_index),
    ...incoming.map((edit) => edit.segment_index)
  ]);
  const result: SpeakerEdit[] = [];
  for (const segmentIndex of touched) {
    const segment = rawSegments[segmentIndex];
    const stored = segment?.speaker ?? null;
    if (!segment || stored === null) continue;
    const length = segment.text.length;
    let runs: RawRun[] = [{ start: 0, end: length, speaker: stored }];
    const storedEdits = existing.filter(
      (edit) => edit.segment_index === segmentIndex && anchorsToSegment(edit, segment.text, stored)
    );
    for (const edit of sortSpeakerEdits(storedEdits)) {
      runs = overlayRun(runs, edit.char_start ?? 0, edit.char_end ?? length, edit.speaker);
    }
    for (const input of incoming) {
      if (input.segment_index !== segmentIndex) continue;
      const start = Math.max(0, input.char_start ?? 0);
      const end = Math.min(length, input.char_end ?? length);
      runs = overlayRun(runs, start, end, input.speaker);
    }
    // Punctuation-only residue (the lone "." left behind when the words
    // around it were reassigned) never deserves its own attribution: absorb
    // it into the preceding run (trailing punctuation follows its sentence),
    // or into the following one at the segment start.
    const hasWords = (run: RawRun) => /[\p{L}\p{N}]/u.test(segment.text.slice(run.start, run.end));
    const absorbed: RawRun[] = [];
    for (const run of runs) {
      const previous = absorbed[absorbed.length - 1];
      if (previous && !hasWords(run)) {
        previous.end = run.end;
        continue;
      }
      absorbed.push({ ...run });
    }
    while (absorbed.length > 1 && !hasWords(absorbed[0])) {
      absorbed[1].start = absorbed[0].start;
      absorbed.shift();
    }
    // Merge adjacent equal-speaker runs so the serialization is canonical.
    const merged: RawRun[] = [];
    for (const run of absorbed) {
      const last = merged[merged.length - 1];
      if (last && last.speaker === run.speaker && last.end === run.start) {
        last.end = run.end;
      } else {
        merged.push({ ...run });
      }
    }
    const changed = merged.filter((run) => run.speaker !== stored && run.start < run.end);
    if (changed.length === 1 && changed[0].start === 0 && changed[0].end === length) {
      result.push({
        segment_index: segmentIndex,
        char_start: null,
        char_end: null,
        original: null,
        original_speaker: stored,
        speaker: changed[0].speaker
      });
      continue;
    }
    for (const run of changed) {
      result.push({
        segment_index: segmentIndex,
        char_start: run.start,
        char_end: run.end,
        original: segment.text.slice(run.start, run.end),
        original_speaker: stored,
        speaker: run.speaker
      });
    }
  }
  return sortSpeakerEdits(result);
}

const SPEAKER_LABEL_RE = /^SPEAKER_(\d{2,})$/;

/** Distinct raw labels in first-appearance order, edits included. */
export function speakerLabels(
  segments: readonly TranscriptSegment[],
  speakerEdits: readonly SpeakerEdit[]
): string[] {
  const labels: string[] = [];
  const seen = new Set<string>();
  const add = (label: string | null | undefined) => {
    if (label && !seen.has(label)) {
      seen.add(label);
      labels.push(label);
    }
  };
  for (const segment of segments) add(segment.speaker);
  for (const edit of speakerEdits) add(edit.speaker);
  return labels;
}

/** The next unused SPEAKER_NN label ("Ny talare" mints raw labels only). */
export function nextSpeakerLabel(labels: readonly string[]): string {
  let max = -1;
  for (const label of labels) {
    const match = SPEAKER_LABEL_RE.exec(label);
    if (match) max = Math.max(max, Number(match[1]));
  }
  return `SPEAKER_${String(max + 1).padStart(2, "0")}`;
}

/** Everything a rendered line needs from one segment's overlays. */
export type SegmentDetails = {
  runs: SegmentRun[];
  geometry: {
    rawText: string;
    displayLength: number;
    displayToRaw: (offset: number, bias: OffsetBias) => number;
  };
};

/** Per-segment attribution runs and selection geometry, keyed by index. */
export function computeSegmentDetails(
  segments: readonly TranscriptSegment[],
  occurrences: readonly CorrectionOccurrence[],
  speakerEdits: readonly SpeakerEdit[]
): Map<number, SegmentDetails> {
  const occurrencesBySegment = new Map<number, CorrectionOccurrence[]>();
  for (const occurrence of occurrences) {
    const list = occurrencesBySegment.get(occurrence.segment_index) ?? [];
    list.push(occurrence);
    occurrencesBySegment.set(occurrence.segment_index, list);
  }
  const editsBySegment = new Map<number, SpeakerEdit[]>();
  for (const edit of speakerEdits) {
    const list = editsBySegment.get(edit.segment_index) ?? [];
    list.push(edit);
    editsBySegment.set(edit.segment_index, list);
  }
  const details = new Map<number, SegmentDetails>();
  for (const segment of segments) {
    const segmentOccurrences = occurrencesBySegment.get(segment.index) ?? [];
    const runs = computeSegmentRuns(
      segment.text,
      segment.speaker,
      segmentOccurrences,
      editsBySegment.get(segment.index) ?? []
    );
    const offsetMap = buildOffsetMap(segment.text, segmentOccurrences);
    details.set(segment.index, {
      runs,
      geometry: {
        rawText: segment.text,
        displayLength: runs[runs.length - 1]?.displayEnd ?? segment.text.length,
        displayToRaw: offsetMap.displayToRaw
      }
    });
  }
  return details;
}
