import type { Eneo, FlowRunTranscriptSourcePage } from "@eneo/eneo-js";

import {
  fileReviewsFromMetadata,
  segmentsFromMetadata,
  type TranscriptFileReview,
  type TranscriptSegment
} from "$lib/features/flows/transcriptSegments";

/**
 * The transcript source behind one transcription attempt, read through the
 * paged route and mapped with the same parsers the embedded metadata used.
 * `present` carries the segments (each stamped with the whole-source hash the
 * corrections API requires) and the file-level speaker review; `omitted` and
 * `unavailable_pre_row` carry no segments and the UI falls back to the
 * rendered transcript lines.
 */
export type TranscriptSourceLoad =
  | {
      status: "present";
      segments: TranscriptSegment[];
      speakerReviews: TranscriptFileReview[];
      sourceHash: string;
    }
  | { status: "omitted"; reason: number }
  | { status: "unavailable_pre_row" };

export type TranscriptSourceRef = { stepId: string; attemptNo: number };

/** The attempt the public step metadata names as the owner of its transcript. */
export function transcriptSourceRef(
  transcription: Record<string, unknown> | null | undefined,
  stepId: string | null | undefined
): TranscriptSourceRef | null {
  const source = transcription?.source;
  if (!stepId || !source || typeof source !== "object" || Array.isArray(source)) return null;
  const attemptNo = (source as Record<string, unknown>).attempt_no;
  return typeof attemptNo === "number" && Number.isInteger(attemptNo) && attemptNo >= 1
    ? { stepId, attemptNo }
    : null;
}

export async function loadTranscriptSource(
  eneo: Eneo,
  params: { flowId: string; runId: string } & TranscriptSourceRef
): Promise<TranscriptSourceLoad> {
  const segments: unknown[] = [];
  let speakerReview: unknown = null;
  let sourceHash: string | null = null;
  let start = 0;
  for (;;) {
    const page: FlowRunTranscriptSourcePage = await eneo.flows.runs.transcriptSource.get({
      ...params,
      startSegmentIndex: start
    });
    if (page.status === "omitted") return { status: "omitted", reason: page.reason };
    if (page.status !== "present") return { status: "unavailable_pre_row" };
    if (start === 0) speakerReview = page.speaker_review ?? null;
    sourceHash ??= page.source_hash;
    segments.push(...page.segments);
    if (page.next_segment_index === null) break;
    if (page.next_segment_index <= start)
      throw new Error("Transcript source paging did not advance");
    start = page.next_segment_index;
  }
  const metadata = { segments, speaker_review: speakerReview, segments_hash: sourceHash };
  const parsed = segmentsFromMetadata(metadata);
  if (!parsed || sourceHash === null) return { status: "unavailable_pre_row" };
  return {
    status: "present",
    segments: parsed,
    speakerReviews: fileReviewsFromMetadata(metadata),
    sourceHash
  };
}
