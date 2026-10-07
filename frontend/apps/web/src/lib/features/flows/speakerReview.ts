import { computeSegmentDetails, buildOffsetMap, type SpeakerEdit } from "./transcriptRuns";
import { formatClock } from "./transcriptSegments";
import type { CorrectionOccurrence } from "./transcriptCorrections";
import type { TranscriptSegment } from "./transcriptSegments";
import { m } from "$lib/paraglide/messages";
export type SpeakerDecision = "confirmed" | "unresolved";
export type EffectiveSpeaker =
  | { kind: "named"; label: string }
  | { kind: "unlabelled" }
  | { kind: "provisional" }
  | { kind: "unresolved" };

export function effectiveSpeaker(
  segment: TranscriptSegment,
  decision?: { speaker: string | null; decision?: SpeakerDecision }
): EffectiveSpeaker {
  if (decision?.decision === "unresolved") return { kind: "unresolved" };
  if (!decision && segment.speakerAttribution === "provisional") return { kind: "provisional" };
  const label = decision ? decision.speaker : segment.speaker;
  return label ? { kind: "named", label } : { kind: "unlabelled" };
}

export function effectiveSpeakerLabel(
  speaker: EffectiveSpeaker,
  displayName: (label: string) => string = (label) => label
): string | null {
  switch (speaker.kind) {
    case "named":
      return displayName(speaker.label);
    case "provisional":
      return m.flow_transcript_review_provisional();
    case "unresolved":
      return m.flow_transcript_review_unresolved();
    case "unlabelled":
      return null;
  }
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
      lines.push(`## ${m.flow_run_transcript_part({ n: segment.fileIndex + 1 })}`, "");
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
      const marker = effective.kind === "provisional" || effective.kind === "unresolved";
      const display = effectiveSpeakerLabel(effective, (label) => names[label]?.trim() || label);
      const label = marker ? `[${display}]` : display;
      lines.push(
        `[${formatClock(start, true)} - ${formatClock(end, true)}] ${label ? label + ": " : ""}${text}`
      );
    }
  }
  return lines.join("\n");
}
