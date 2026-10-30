import { shownToRaw, type Occurrence } from "./transcript-corrections";

/**
 * Text the reviewer marked in the transcript itself, as spans of the lines'
 * raw text: what reassigning a speaker anchors to. Every rendered part of a
 * line carries its line (`data-part-of`) and where it starts in the line's
 * corrected text (`data-shown-start`); a selection is read per part, merged
 * per line and mapped back through the line's corrections. Whitespace at a
 * span's ends is left out, and a span with no text is dropped.
 */

export type SelectedSpan = { segmentIndex: number; start: number; end: number };

export type LineText = { raw: string; occurrences: readonly Occurrence[] };

/** The attributes a rendered part carries, for `selectedSpans`. */
export function partAttributes(segmentIndex: number, shownStart: number) {
  return { "data-part-of": segmentIndex, "data-shown-start": shownStart };
}

/** How many characters of `element`'s text come before the boundary (node, offset) inside it. */
function textBefore(element: Element, node: Node, offset: number): number {
  const range = element.ownerDocument.createRange();
  range.setStart(element, 0);
  range.setEnd(node, offset);
  return range.toString().length;
}

export function selectedSpans(
  container: Element,
  range: Range,
  lineText: (segmentIndex: number) => LineText | null
): SelectedSpan[] {
  const covered = new Map<number, { start: number; end: number }>();
  for (const element of container.querySelectorAll<HTMLElement>("[data-part-of]")) {
    if (!range.intersectsNode(element)) continue;
    const segmentIndex = Number(element.dataset.partOf);
    const offset = Number(element.dataset.shownStart ?? 0);
    if (!Number.isInteger(segmentIndex) || !Number.isFinite(offset)) continue;
    const length = element.textContent?.length ?? 0;
    const from = element.contains(range.startContainer)
      ? textBefore(element, range.startContainer, range.startOffset)
      : 0;
    const to = element.contains(range.endContainer)
      ? textBefore(element, range.endContainer, range.endOffset)
      : length;
    if (from >= to) continue;
    const known = covered.get(segmentIndex);
    covered.set(segmentIndex, {
      start: Math.min(known?.start ?? Infinity, offset + from),
      end: Math.max(known?.end ?? -Infinity, offset + to)
    });
  }
  const spans: SelectedSpan[] = [];
  for (const [segmentIndex, shown] of [...covered].sort(([a], [b]) => a - b)) {
    const line = lineText(segmentIndex);
    if (!line) continue;
    let start = shownToRaw(line.raw, line.occurrences, shown.start, "start");
    let end = shownToRaw(line.raw, line.occurrences, shown.end, "end");
    start = Math.max(0, Math.min(start, line.raw.length));
    end = Math.max(0, Math.min(end, line.raw.length));
    while (start < end && /\s/.test(line.raw[start]!)) start += 1;
    while (end > start && /\s/.test(line.raw[end - 1]!)) end -= 1;
    if (start < end) spans.push({ segmentIndex, start, end });
  }
  return spans;
}
