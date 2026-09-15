import { computeSegmentDetails, buildOffsetMap, type SpeakerEdit } from "./transcriptRuns";
import { formatClock } from "./transcriptSegments";
import type { CorrectionOccurrence } from "./transcriptCorrections";
import type { TranscriptSegment } from "./transcriptSegments";
export type SpeakerDecision = "confirmed" | "unresolved";
export const PROVISIONAL_SPEAKER = "Överlappande tal – osäker talare";
export const UNRESOLVED_SPEAKER = "Talare går inte att avgöra";

export function effectiveSpeaker(
  segment: TranscriptSegment,
  decision?: { speaker: string | null; decision?: SpeakerDecision }
): string | null {
  if (decision) return decision.decision === "unresolved" ? UNRESOLVED_SPEAKER : decision.speaker;
  if (segment.speakerAttribution === "provisional") return PROVISIONAL_SPEAKER;
  return segment.speaker;
}

/** Plain-text export of the same overlay the player displays. */
export function renderReviewedTranscript(
  segments: readonly TranscriptSegment[],
  occurrences: readonly CorrectionOccurrence[],
  edits: readonly SpeakerEdit[],
  names: Readonly<Record<string, string | null | undefined>> = {}
): string {
  const details = computeSegmentDetails(segments, occurrences, edits);
  const lines: string[] = [];
  let fileIndex = -1;
  const multipleFiles = new Set(segments.map((segment) => segment.fileIndex)).size > 1;
  for (const segment of segments) {
    if (multipleFiles && fileIndex !== segment.fileIndex) {
      if (lines.length) lines.push("");
      lines.push(`## Del ${segment.fileIndex + 1}`, "");
      fileIndex = segment.fileIndex;
    }
    const detail = details.get(segment.index);
    const offsetMap = buildOffsetMap(
      segment.text,
      occurrences.filter((item) => item.segment_index === segment.index)
    );
    for (const run of detail?.runs ?? []) {
      const text = run.text.trim();
      if (!text) continue;
      const words =
        detail && detail.runs.length > 1
          ? (segment.words ?? []).filter(
              (word) =>
                word.charStart >= 0 &&
                offsetMap.rawToDisplay(word.charStart) < run.displayEnd &&
                offsetMap.rawToDisplay(word.charEnd) > run.displayStart
            )
          : [];
      const start = words.length ? Math.min(...words.map((word) => word.start)) : segment.start;
      const end = words.length ? Math.max(...words.map((word) => word.end)) : segment.end;
      const effective = effectiveSpeaker(segment, run.overridden ? run : undefined);
      const marker = effective === PROVISIONAL_SPEAKER || effective === UNRESOLVED_SPEAKER;
      const label = marker
        ? `[${effective}]`
        : effective
          ? names[effective]?.trim() || effective
          : null;
      lines.push(
        `[${formatClock(start, true)} - ${formatClock(end, true)}] ${label ? label + ": " : ""}${text}`
      );
    }
  }
  return lines.join("\n");
}
