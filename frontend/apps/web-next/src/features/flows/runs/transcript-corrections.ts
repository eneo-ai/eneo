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

/**
 * Whether two sets say the same, whatever order their entries come in (the
 * core answers a save in its own order) and however empty names are kept.
 */
export function sameCorrections(a: CorrectionSet, b: CorrectionSet): boolean {
  const key = (set: CorrectionSet) =>
    JSON.stringify({
      occurrences: sortOccurrences(set.occurrences).map((item) => [
        item.segment_index,
        item.char_start,
        item.char_end,
        item.original,
        item.corrected
      ]),
      speakers: set.speakerEdits
        .map((edit) => [
          edit.segment_index,
          edit.char_start ?? null,
          edit.char_end ?? null,
          edit.original ?? null,
          edit.original_speaker ?? null,
          edit.speaker ?? null,
          edit.decision ?? "confirmed"
        ])
        .sort((x, y) => JSON.stringify(x).localeCompare(JSON.stringify(y))),
      names: Object.entries(set.names)
        .filter(([, name]) => name?.trim())
        .sort(([x], [y]) => x.localeCompare(y))
    });
  return key(a) === key(b);
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

export type SpeakerDecision = "confirmed" | "unresolved";

/** One part of a shown line: whose words they are once corrections and speaker edits apply. */
export type LinePart = {
  /** The part's speaker label, or null for no speaker. */
  speaker: string | null;
  /** A speaker edit gave this part its speaker. */
  overridden: boolean;
  decision: SpeakerDecision | null;
  /** The part's text with the line's text corrections applied. */
  text: string;
  rawStart: number;
  rawEnd: number;
};

function anchors(edit: WireSpeakerEdit, rawText: string, segmentSpeaker: string | null): boolean {
  if (edit.original_speaker !== segmentSpeaker) return false;
  if (edit.char_start == null || edit.char_end == null) return edit.original == null;
  return (
    edit.char_start >= 0 &&
    edit.char_end <= rawText.length &&
    edit.char_start < edit.char_end &&
    rawText.slice(edit.char_start, edit.char_end) === edit.original
  );
}

/**
 * A raw offset in the corrected text. Monotone; an offset inside a replaced
 * span stays within its replacement.
 */
function rawToShown(applicable: readonly Occurrence[], offset: number): number {
  let delta = 0;
  for (const occurrence of applicable) {
    if (occurrence.char_end <= offset) {
      delta += occurrence.corrected.length - (occurrence.char_end - occurrence.char_start);
    } else if (occurrence.char_start < offset) {
      return (
        occurrence.char_start +
        delta +
        Math.min(offset - occurrence.char_start, occurrence.corrected.length)
      );
    } else {
      break;
    }
  }
  return offset + delta;
}

/**
 * An offset in the corrected text as a raw offset; inside a replaced span it
 * snaps to the span's start or end (`bias`).
 */
export function shownToRaw(
  rawText: string,
  occurrences: readonly Occurrence[],
  offset: number,
  bias: "start" | "end"
): number {
  let delta = 0;
  for (const occurrence of applicableOccurrences(rawText, occurrences)) {
    const start = occurrence.char_start + delta;
    const end = start + occurrence.corrected.length;
    if (offset <= start) return offset - delta;
    if (offset < end) return bias === "start" ? occurrence.char_start : occurrence.char_end;
    delta += occurrence.corrected.length - (occurrence.char_end - occurrence.char_start);
  }
  return offset - delta;
}

/**
 * A line's parts: one, with the line's own speaker, unless speaker edits
 * reassign it; a whole-line edit gives one reassigned part, span edits split
 * the line. Overlapping spans can only mean corrupt storage and are skipped.
 */
export function lineParts(
  rawText: string,
  segmentSpeaker: string | null,
  occurrences: readonly Occurrence[],
  speakerEdits: readonly WireSpeakerEdit[]
): LinePart[] {
  const applicable = applicableOccurrences(rawText, occurrences);
  const shown = correctedText(rawText, applicable);
  const base: LinePart = {
    speaker: segmentSpeaker,
    overridden: false,
    decision: null,
    text: shown,
    rawStart: 0,
    rawEnd: rawText.length
  };
  const anchored = speakerEdits.filter((edit) => anchors(edit, rawText, segmentSpeaker));
  const whole = anchored.find((edit) => edit.char_start == null);
  if (whole) {
    return [
      { ...base, speaker: whole.speaker, overridden: true, decision: whole.decision ?? "confirmed" }
    ];
  }
  const spans = anchored
    .filter((edit) => edit.char_start != null)
    .sort((a, b) => (a.char_start ?? 0) - (b.char_start ?? 0));
  if (spans.length === 0) return [base];
  const parts: LinePart[] = [];
  const push = (
    rawStart: number,
    rawEnd: number,
    speaker: string | null,
    decision: SpeakerDecision | null
  ) => {
    const start = rawToShown(applicable, rawStart);
    const end = rawToShown(applicable, rawEnd);
    if (start >= end) return;
    parts.push({
      speaker,
      overridden: decision !== null,
      decision,
      text: shown.slice(start, end),
      rawStart,
      rawEnd
    });
  };
  let cursor = 0;
  for (const edit of spans) {
    const start = edit.char_start ?? 0;
    const end = edit.char_end ?? 0;
    if (start < cursor) continue;
    if (cursor < start) push(cursor, start, segmentSpeaker, null);
    push(start, end, edit.speaker, edit.decision ?? "confirmed");
    cursor = end;
  }
  if (cursor < rawText.length) push(cursor, rawText.length, segmentSpeaker, null);
  return parts.length > 0 ? parts : [base];
}

type Run = { start: number; end: number; speaker: string | null; decision: SpeakerDecision | null };

function overlay(runs: Run[], next: Run): Run[] {
  if (next.start >= next.end) return runs;
  const kept: Run[] = [];
  for (const run of runs) {
    if (run.end <= next.start || run.start >= next.end) {
      kept.push(run);
      continue;
    }
    if (run.start < next.start) kept.push({ ...run, end: next.start });
    if (run.end > next.end) kept.push({ ...run, start: next.end });
  }
  return [...kept, next].sort((a, b) => a.start - b.start);
}

/**
 * The set with part of a line (`span` in raw offsets, or null for the whole
 * line) given to `speaker` with `decision`, or reset to the line's own
 * speaker (`speaker` undefined). Later decisions win within their span;
 * neighbouring parts with the same speaker and decision merge, and a part
 * that is only spaces or punctuation joins its neighbour.
 */
export function withSpeaker(
  set: CorrectionSet,
  segment: Pick<TranscriptSegment, "index" | "text" | "speaker">,
  span: { start: number; end: number } | null,
  change: { speaker: string | null; decision: SpeakerDecision } | "reset"
): CorrectionSet {
  const length = segment.text.length;
  const own = set.speakerEdits.filter((edit) => edit.segment_index === segment.index);
  let runs: Run[] = [{ start: 0, end: length, speaker: segment.speaker, decision: null }];
  const sorted = own
    .filter((edit) => anchors(edit, segment.text, segment.speaker))
    .sort((a, b) => (a.char_start ?? -1) - (b.char_start ?? -1));
  for (const edit of sorted) {
    runs = overlay(runs, {
      start: edit.char_start ?? 0,
      end: edit.char_end ?? length,
      speaker: edit.speaker,
      decision: edit.decision ?? "confirmed"
    });
  }
  const start = Math.max(0, span?.start ?? 0);
  const end = Math.min(length, span?.end ?? length);
  runs = overlay(
    runs,
    change === "reset"
      ? { start, end, speaker: segment.speaker, decision: null }
      : { start, end, speaker: change.speaker, decision: change.decision }
  );
  const hasWords = (run: Run) => /[\p{L}\p{N}]/u.test(segment.text.slice(run.start, run.end));
  const absorbed: Run[] = [];
  for (const run of runs) {
    const previous = absorbed.at(-1);
    if (previous && !hasWords(run)) previous.end = run.end;
    else absorbed.push({ ...run });
  }
  while (absorbed.length > 1 && !hasWords(absorbed[0]!)) {
    absorbed[1]!.start = absorbed[0]!.start;
    absorbed.shift();
  }
  const merged: Run[] = [];
  for (const run of absorbed) {
    const last = merged.at(-1);
    if (last && last.speaker === run.speaker && last.decision === run.decision) last.end = run.end;
    else merged.push({ ...run });
  }
  const edits: WireSpeakerEdit[] = merged
    .filter((run) => run.decision !== null && run.start < run.end)
    .map((run) => {
      const whole = run.start === 0 && run.end === length;
      return {
        segment_index: segment.index,
        char_start: whole ? null : run.start,
        char_end: whole ? null : run.end,
        original: whole ? null : segment.text.slice(run.start, run.end),
        original_speaker: segment.speaker,
        speaker: run.speaker,
        decision: run.decision ?? "confirmed"
      };
    });
  return {
    ...set,
    speakerEdits: [
      ...set.speakerEdits.filter((edit) => edit.segment_index !== segment.index),
      ...edits
    ].sort(
      (a, b) => a.segment_index - b.segment_index || (a.char_start ?? -1) - (b.char_start ?? -1)
    )
  };
}

/** The speaker labels of a transcript and of its speaker edits, in order of first appearance. */
export function knownSpeakers(
  segments: readonly Pick<TranscriptSegment, "speaker">[],
  speakerEdits: readonly Pick<WireSpeakerEdit, "speaker">[]
): string[] {
  const labels = [
    ...segments.map((segment) => segment.speaker),
    ...speakerEdits.map((edit) => edit.speaker)
  ];
  return [...new Set(labels.filter((label): label is string => Boolean(label)))];
}

/** The next unused `SPEAKER_NN` label: a new speaker split out of a merged one. */
export function nextSpeakerLabel(labels: readonly string[]): string {
  let max = -1;
  for (const label of labels) {
    const match = /^SPEAKER_(\d{2,})$/.exec(label);
    if (match) max = Math.max(max, Number(match[1]));
  }
  return `SPEAKER_${String(max + 1).padStart(2, "0")}`;
}
