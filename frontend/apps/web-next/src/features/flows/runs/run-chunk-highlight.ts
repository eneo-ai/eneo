/**
 * Where the passages a step retrieved sit in their source document, for
 * the knowledge source viewer: the document cut into plain and highlighted
 * pieces, each highlighted piece naming the passages it belongs to. A
 * passage is found by its first exact occurrence (trimmed), as the core
 * cut it from the same text; one the document no longer holds is reported
 * as not found rather than guessed at.
 */

export type HighlightSegment = {
  text: string;
  /** Indexes of the passages this piece belongs to; empty for plain text. */
  passages: number[];
  /** Passages whose first piece this is, so the viewer can go to them. */
  starts: number[];
};

export function highlightSegments(
  document: string,
  passages: readonly string[]
): { segments: HighlightSegment[]; found: boolean[] } {
  const spans = passages.map((passage) => {
    const text = passage.trim();
    if (!text) return null;
    const start = document.indexOf(text);
    return start === -1 ? null : { start, end: start + text.length };
  });
  const cuts = new Set<number>([0, document.length]);
  for (const span of spans) {
    if (!span) continue;
    cuts.add(span.start);
    cuts.add(span.end);
  }
  const points = [...cuts].sort((a, b) => a - b);
  const segments: HighlightSegment[] = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const from = points[index]!;
    const to = points[index + 1]!;
    if (to <= from) continue;
    const covering: number[] = [];
    const starts: number[] = [];
    spans.forEach((span, passage) => {
      if (span && span.start <= from && to <= span.end) {
        covering.push(passage);
        if (span.start === from) starts.push(passage);
      }
    });
    segments.push({ text: document.slice(from, to), passages: covering, starts });
  }
  return { segments, found: spans.map((span) => span !== null) };
}

export type RelevanceLevel = "high" | "moderate" | "low";

/** The words a passage's similarity score is shown with. */
export function relevanceLevel(score: number): RelevanceLevel {
  if (score >= 0.5) return "high";
  if (score >= 0.3) return "moderate";
  return "low";
}
