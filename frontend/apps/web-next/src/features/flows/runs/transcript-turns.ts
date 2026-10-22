import type { ShownSegment } from "./transcript";

/**
 * Speaker turns: consecutive parts of the shown lines that the same speaker
 * said, read as one paragraph instead of the transcription's fragments.
 * The line stays the unit underneath: every part keeps its line and where
 * it stands in the line's text, so playing, selecting and reassigning work
 * on turns as on lines. A new file, or a part whose speaker is marked
 * unsure, always starts a turn of its own. Pure.
 */

export type TurnMarker = "unresolved" | "unsure";

export type TurnPart = {
  /** The line's place among the shown lines. */
  position: number;
  segmentIndex: number;
  text: string;
  /** Where the part starts in the line's corrected text. */
  shownStart: number;
};

export type Turn = {
  speaker: string | null;
  name: string | null;
  marker: TurnMarker | null;
  fileIndex: number;
  /** Seconds into its file where the turn's first line starts. */
  start: number;
  parts: TurnPart[];
};

function markerOf(segment: ShownSegment, part: ShownSegment["parts"][number]): TurnMarker | null {
  if (part.decision === "unresolved") return "unresolved";
  return segment.parts.length === 1 && segment.unsure ? "unsure" : null;
}

export function transcriptTurns(shown: readonly ShownSegment[]): Turn[] {
  const turns: Turn[] = [];
  shown.forEach((segment, position) => {
    let shownStart = 0;
    for (const part of segment.parts) {
      const start = shownStart;
      shownStart += part.text.length;
      if (!part.text.trim()) continue;
      const marker = markerOf(segment, part);
      const last = turns.at(-1);
      const piece: TurnPart = {
        position,
        segmentIndex: segment.index,
        text: part.text,
        shownStart: start
      };
      if (
        last &&
        last.speaker === part.speaker &&
        last.fileIndex === segment.fileIndex &&
        last.marker === null &&
        marker === null
      ) {
        last.parts.push(piece);
        continue;
      }
      turns.push({
        speaker: part.speaker,
        name: part.name,
        marker,
        fileIndex: segment.fileIndex,
        start: segment.start,
        parts: [piece]
      });
    }
  });
  return turns;
}
