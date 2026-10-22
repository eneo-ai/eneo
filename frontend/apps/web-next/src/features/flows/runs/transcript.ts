import type { Schema } from "@/lib/api/models";
import type { RunStep } from "./runs-api";

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

/** A transcription step of the run and the attempt that owns its transcript. */
export type TranscriptTarget = { stepId: string; stepOrder: number; attemptNo: number };

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
      return [{ stepId: step.step_id, stepOrder: step.step_order, attemptNo }];
    })
    .sort((a, b) => a.stepOrder - b.stepOrder);
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
    text: item.text
  }));
}

/** A line with the saved corrections applied, and its speaker's shown name. */
export type ShownSegment = TranscriptSegment & { label: string | null; name: string | null };

/**
 * Applies saved corrections: each occurrence replaces exactly its span of
 * the raw text (later spans first, so earlier offsets hold); a whole-line
 * speaker edit reassigns the line; a speaker's name replaces its label.
 * Span-level speaker edits (part of a line to another speaker) are not
 * shown split; the line keeps its own speaker.
 */
export function shownSegments(
  segments: readonly TranscriptSegment[],
  corrections: Pick<TranscriptCorrections, "occurrences" | "speaker_edits" | "speaker_names"> | null
): ShownSegment[] {
  const occurrences = corrections?.occurrences ?? [];
  const edits = (corrections?.speaker_edits ?? []).filter(
    (edit) => edit.char_start == null && edit.char_end == null
  );
  const names = corrections?.speaker_names ?? {};
  return segments.map((segment) => {
    let text = segment.text;
    const own = occurrences
      .filter((occurrence) => occurrence.segment_index === segment.index)
      .sort((a, b) => b.char_start - a.char_start);
    for (const occurrence of own) {
      if (text.slice(occurrence.char_start, occurrence.char_end) !== occurrence.original) continue;
      text =
        text.slice(0, occurrence.char_start) +
        occurrence.corrected +
        text.slice(occurrence.char_end);
    }
    const edit = edits.find((item) => item.segment_index === segment.index);
    const label = edit && edit.decision !== "unresolved" ? edit.speaker : segment.speaker;
    const name = label ? names[label]?.trim() || null : null;
    return { ...segment, text, label, name };
  });
}

/** The speaker labels a transcript uses, in order of first appearance. */
export function speakerLabels(segments: readonly Pick<ShownSegment, "label">[]): string[] {
  return [...new Set(segments.flatMap((segment) => (segment.label ? [segment.label] : [])))];
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
