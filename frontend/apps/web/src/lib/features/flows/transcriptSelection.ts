/**
 * Maps a DOM selection over the rendered transcript back to raw-text spans.
 *
 * Every rendered part carries its own anchors: `data-run-text`,
 * `data-segment-index`, and `data-display-start` (display-space offset within
 * its segment). A selection resolves per part, merges per segment, then maps
 * into raw space through each segment's correction offset map.
 */

import type { OffsetBias } from "$lib/features/flows/transcriptRuns";

/** A raw-space reassignment target produced from a selection. */
export type SelectionSpan = {
  segmentIndex: number;
  charStart: number;
  charEnd: number;
};

/** What the resolver needs to know about one rendered segment. */
export type SegmentGeometry = {
  rawText: string;
  displayLength: number;
  displayToRaw: (offset: number, bias: OffsetBias) => number;
};

/** -1: the boundary lies before `node`; 0: inside it; 1: after it. */
function compareBoundary(container: Node, offset: number, node: Node): -1 | 0 | 1 {
  if (container === node || node.contains(container)) return 0;
  let reference: Node | null = container;
  if (container.nodeType !== Node.TEXT_NODE) {
    reference = container.childNodes[offset] ?? null;
    if (reference === null) {
      // Boundary sits after the container's last child.
      if (container.contains(node)) return 1;
      const relation = container.compareDocumentPosition(node);
      return relation & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
    }
    if (reference === node || reference.contains(node)) return -1;
    if (node.contains(reference)) return 0;
  }
  const relation = reference.compareDocumentPosition(node);
  return relation & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
}

/** Character offset of a boundary that lies inside `span`. */
function offsetWithinSpan(span: HTMLElement, container: Node, offset: number): number {
  if (container === span) {
    let total = 0;
    for (let index = 0; index < Math.min(offset, span.childNodes.length); index += 1) {
      total += (span.childNodes[index].textContent ?? "").length;
    }
    return total;
  }
  let preceding = 0;
  for (const child of span.childNodes) {
    if (child === container || child.contains(container)) {
      return preceding + (container.nodeType === Node.TEXT_NODE ? offset : 0);
    }
    preceding += (child.textContent ?? "").length;
  }
  return preceding;
}

/**
 * Raw-space spans covered by a (forward) Range over the transcript: one span
 * per touched segment, whitespace-trimmed in raw space, empties dropped.
 */
export function selectionToSpans(
  listEl: HTMLElement,
  range: Range,
  geometryOf: (segmentIndex: number) => SegmentGeometry | null
): SelectionSpan[] {
  const bySegment = new Map<number, { displayStart: number; displayEnd: number }>();
  for (const span of listEl.querySelectorAll<HTMLElement>("[data-run-text]")) {
    const segmentIndex = Number(span.dataset.segmentIndex);
    if (!Number.isInteger(segmentIndex)) continue;
    const partStart = Number(span.dataset.displayStart ?? 0);
    const length = (span.textContent ?? "").length;
    const startSide = compareBoundary(range.startContainer, range.startOffset, span);
    const endSide = compareBoundary(range.endContainer, range.endOffset, span);
    // The selection misses this part when it starts after it or ends before it.
    if (startSide === 1 || endSide === -1) continue;
    const selStart =
      startSide === -1 ? 0 : offsetWithinSpan(span, range.startContainer, range.startOffset);
    const selEnd =
      endSide === 1 ? length : offsetWithinSpan(span, range.endContainer, range.endOffset);
    if (selStart >= selEnd) continue;
    const displayStart = partStart + selStart;
    const displayEnd = partStart + selEnd;
    const existing = bySegment.get(segmentIndex);
    bySegment.set(segmentIndex, {
      displayStart: Math.min(existing?.displayStart ?? displayStart, displayStart),
      displayEnd: Math.max(existing?.displayEnd ?? displayEnd, displayEnd)
    });
  }

  const spans: SelectionSpan[] = [];
  for (const segmentIndex of [...bySegment.keys()].sort((a, b) => a - b)) {
    const geometry = geometryOf(segmentIndex);
    if (!geometry) continue;
    const covered = bySegment.get(segmentIndex)!;
    const displayStart = Math.max(0, Math.min(covered.displayStart, geometry.displayLength));
    const displayEnd = Math.max(0, Math.min(covered.displayEnd, geometry.displayLength));
    if (displayStart >= displayEnd) continue;
    let charStart = geometry.displayToRaw(displayStart, "start");
    let charEnd = geometry.displayToRaw(displayEnd, "end");
    const raw = geometry.rawText;
    while (charStart < charEnd && /\s/.test(raw[charStart])) charStart += 1;
    while (charEnd > charStart && /\s/.test(raw[charEnd - 1])) charEnd -= 1;
    if (charStart >= charEnd) continue;
    spans.push({ segmentIndex, charStart, charEnd });
  }
  return spans;
}
