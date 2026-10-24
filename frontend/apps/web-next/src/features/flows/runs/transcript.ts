import type { Schema } from "@/lib/api/models";
import type { ReviewCheckpoint, RunStep } from "./runs-api";
import {
  applicableOccurrences,
  correctionSet,
  lineParts,
  type CorrectionSet,
  type LinePart,
  type SpeakerDecision
} from "./transcript-corrections";

/**
 * A run's transcript as a reader sees it: the transcription step's
 * segments (the core stores them per attempt and returns them in pages),
 * with the saved corrections applied: replaced text, reassigned speakers
 * and the names given to speakers. Pure; the transcript section renders it.
 */

export type TranscriptCorrections = Schema<"FlowTranscriptCorrectionsPublic">;
export type TranscriptSourceSegment = Schema<"TranscriptSourceSegmentPublic">;

/**
 * `TranscriptSourceOmissionReason` by name. The wire carries the numbers; the
 * names are the ones the API documents for them.
 */
export const OMISSION_REASON = {
  TOO_LARGE: 1,
  NO_SEGMENTS: 2,
  SEGMENTS_UNAVAILABLE: 3
} as const satisfies Record<string, Schema<"TranscriptSourceOmissionReason">>;

/**
 * A transcription step of the run, the attempt that owns its transcript, and
 * its audio files in upload order (a line's `fileIndex` counts in them).
 */
export type TranscriptTarget = {
  stepId: string;
  stepOrder: number;
  attemptNo: number;
  fileIds: string[];
};

export type TranscriptSegment = {
  index: number;
  /** Which audio file (in upload order) the times belong to. */
  fileIndex: number;
  /** Seconds from the start of that file. */
  start: number;
  end: number;
  /** The diarization label (`SPEAKER_00`), or null when the line has none. */
  speaker: string | null;
  text: string;
  /** The speaker review's overlaps the line falls in, by id. */
  overlapIds?: string[];
  /** Overlapping speech made the speaker service unsure of the line's speaker. */
  provisional?: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * The steps whose input names audio files and the attempt that owns their
 * transcript (`input_payload_json.transcription`), in step order.
 */
export function transcriptTargets(
  steps: readonly RunStep[] | null | undefined
): TranscriptTarget[] {
  return (steps ?? [])
    .flatMap((step) => {
      const transcription = step.input_payload_json?.transcription;
      if (!isRecord(transcription)) return [];
      const files = Array.isArray(transcription.file_ids) ? transcription.file_ids : [];
      const source = isRecord(transcription.source) ? transcription.source : null;
      const attemptNo = finite(source?.attempt_no);
      if (
        files.length === 0 ||
        attemptNo === null ||
        !Number.isInteger(attemptNo) ||
        attemptNo < 1
      ) {
        return [];
      }
      return [
        {
          stepId: step.step_id,
          stepOrder: step.step_order,
          attemptNo,
          fileIds: files.filter((id): id is string => typeof id === "string")
        }
      ];
    })
    .sort((a, b) => a.stepOrder - b.stepOrder);
}

/**
 * The transcript a review checkpoint is about: its own step's when the step
 * transcribed, or, for a speaker mapping, the transcription before it. Null
 * when the review is about something else.
 */
export function reviewTranscriptTarget(
  checkpoint: Pick<ReviewCheckpoint, "step_id" | "step_order">,
  speakerMapping: boolean,
  steps: readonly RunStep[] | null | undefined
): TranscriptTarget | null {
  const targets = transcriptTargets(steps);
  const own = targets.find((target) => target.stepId === checkpoint.step_id);
  if (own) return own;
  if (!speakerMapping) return null;
  return targets.filter((target) => target.stepOrder < checkpoint.step_order).at(-1) ?? null;
}

/**
 * The structured lines of a transcript source page, as the screens read them.
 * An end before the start is read as the start.
 */
export function parseSegments(raw: readonly TranscriptSourceSegment[]): TranscriptSegment[] {
  return raw.map((item) => ({
    index: item.segment_index,
    fileIndex: item.file_index,
    start: item.start,
    end: Math.max(item.start, item.end),
    speaker: item.speaker || null,
    text: item.text,
    ...(item.overlap_ids?.length ? { overlapIds: item.overlap_ids } : {}),
    ...(item.speaker_attribution === "provisional" ? { provisional: true } : {})
  }));
}

/** A part of a shown line with its speaker's label and shown name. */
export type ShownPart = LinePart & { name: string | null };

/**
 * A line with the saved corrections applied: its corrected text (`text`)
 * and raw text (`raw`), whether a text correction changed it, its parts by
 * speaker (more than one when part of the line was given to another
 * speaker), and the line's speaker label and shown name.
 */
export type ShownSegment = TranscriptSegment & {
  raw: string;
  label: string | null;
  name: string | null;
  corrected: boolean;
  parts: ShownPart[];
  /** How sure the reviewer was of a whole-line reassignment; null without one. */
  decision: SpeakerDecision | null;
  /**
   * The speaker service was unsure of the line's speaker, and no reviewer
   * has decided it since.
   */
  unsure: boolean;
};

/**
 * Applies saved corrections: each text correction replaces exactly its span
 * of the raw text; speaker edits give the line, or parts of it, to another
 * speaker; a speaker's name replaces its label. Anchors that no longer match
 * are left out.
 */
export function shownSegments(
  segments: readonly TranscriptSegment[],
  corrections: Pick<TranscriptCorrections, "occurrences" | "speaker_edits" | "speaker_names"> | null
): ShownSegment[] {
  return shownSegmentsOf(segments, correctionSet(corrections, segments));
}

function bySegment<T extends { segment_index: number }>(items: readonly T[]): Map<number, T[]> {
  const grouped = new Map<number, T[]>();
  for (const item of items) {
    const group = grouped.get(item.segment_index);
    if (group) group.push(item);
    else grouped.set(item.segment_index, [item]);
  }
  return grouped;
}

/** The lines with a set of corrections as the editor holds it (a draft not saved yet). */
export function shownSegmentsOf(
  segments: readonly TranscriptSegment[],
  set: CorrectionSet
): ShownSegment[] {
  const nameOf = (label: string | null) => (label ? set.names[label]?.trim() || null : null);
  // Each line's corrections, in the order they were made, gathered once.
  const occurrences = bySegment(set.occurrences);
  const speakerEdits = bySegment(set.speakerEdits);
  return segments.map((segment) => {
    const own = occurrences.get(segment.index) ?? [];
    const corrected = applicableOccurrences(segment.text, own).length > 0;
    const parts = lineParts(
      segment.text,
      segment.speaker,
      own,
      speakerEdits.get(segment.index) ?? []
    ).map((part) => ({ ...part, name: nameOf(part.speaker) }));
    const single = parts.length === 1 ? parts[0]! : null;
    const label = single ? single.speaker : segment.speaker;
    return {
      ...segment,
      text: parts.map((part) => part.text).join(""),
      raw: segment.text,
      label,
      name: nameOf(label),
      corrected,
      parts,
      decision: single?.decision ?? null,
      unsure: Boolean(segment.provisional) && !parts.some((part) => part.overridden)
    };
  });
}

/** The speaker labels a transcript uses, in order of first appearance. */
export function speakerLabels(segments: readonly Pick<ShownSegment, "parts">[]): string[] {
  return [
    ...new Set(
      segments.flatMap((segment) =>
        segment.parts.flatMap((part) => (part.speaker ? [part.speaker] : []))
      )
    )
  ];
}

/** Seconds as `m:ss`, or `h:mm:ss` past the hour. */
export function clockTime(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = String(whole % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

/**
 * The edit request that sets the speakers' names and keeps every other
 * saved correction as it is (the endpoint replaces the whole set).
 */
export function speakerNamesRequest(
  corrections: TranscriptCorrections | null,
  sourceHash: string,
  names: Record<string, string>
): Schema<"FlowTranscriptCorrectionsEditRequest"> {
  const schemaVersion = corrections?.schema_version;
  return {
    expected_revision: corrections?.revision ?? null,
    segments_hash: corrections?.segments_hash ?? sourceHash,
    occurrences: corrections?.occurrences ?? [],
    speaker_edits: corrections?.speaker_edits ?? [],
    speaker_names: Object.fromEntries(
      Object.entries(names).map(([label, name]) => [label, name.trim() || null])
    ),
    ...(schemaVersion === 2 || schemaVersion === 3 ? { schema_version: schemaVersion } : {})
  };
}
