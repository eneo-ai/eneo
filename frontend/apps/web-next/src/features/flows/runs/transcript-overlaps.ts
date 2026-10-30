import type { TranscriptSpeakerReview } from "./runs-api";
import type { ShownSegment } from "./transcript";

/**
 * Where the speaker service heard more than one voice at once (its speaker
 * review), and the lines a reviewer should check there: lines in an overlap
 * whose speaker the service was unsure of stay open until the reviewer
 * decides who said them. Pure; the transcript renders it.
 */

export type Overlap = {
  id: string;
  fileIndex: number;
  start: number;
  end: number;
  /** How many voices the service heard; null when it did not say. */
  voices: number | null;
  /** The lines in the overlap, by position in the shown lines. */
  lines: number[];
  /** Lines in the overlap whose speaker is still to be decided. */
  open: number;
};

/**
 * The review's overlaps with the lines they cover, in file and time order.
 * Malformed entries (no id, an end before the start) are left out.
 */
export function overlaps(
  review: TranscriptSpeakerReview | null | undefined,
  shown: readonly Pick<ShownSegment, "overlapIds" | "unsure">[]
): Overlap[] {
  const found: Overlap[] = [];
  for (const file of review?.files ?? []) {
    for (const overlap of file.overlaps ?? []) {
      if (!overlap.id || !(overlap.end > overlap.start)) continue;
      const lines = shown.flatMap((segment, position) =>
        segment.overlapIds?.includes(overlap.id) ? [position] : []
      );
      found.push({
        id: overlap.id,
        fileIndex: file.file_index,
        start: overlap.start,
        end: overlap.end,
        voices:
          typeof overlap.detected_speaker_count === "number"
            ? overlap.detected_speaker_count
            : null,
        lines,
        open: lines.filter((position) => shown[position]?.unsure).length
      });
    }
  }
  return found.sort((a, b) => a.fileIndex - b.fileIndex || a.start - b.start);
}

/** Whether the speaker service looked for overlapping speech in any file and could not. */
export function overlapDetectionUnavailable(
  review: TranscriptSpeakerReview | null | undefined
): boolean {
  return (review?.files ?? []).some((file) => file.overlap_detection === "unavailable");
}
