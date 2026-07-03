import type { PromptSegment, VariableCategory } from "$lib/features/flows/flowVariableTokens";

/**
 * A prompt segment for the editor's mirror layer, plus an optional zero-width
 * `marker` segment spliced at the caret so the autocomplete popover can measure
 * its screen position from the marker's DOM rect.
 */
export type MirrorSegment = {
  type: "text" | "variable" | "marker";
  value: string;
  category?: VariableCategory;
};

export function toMirror(seg: PromptSegment): MirrorSegment {
  return seg.type === "variable"
    ? { type: "variable", value: seg.value, category: seg.category }
    : { type: "text", value: seg.value };
}

/**
 * Rebuild the mirror segments, splicing a zero-width marker at the caret
 * (`anchorIdx`) while the autocomplete popover is open. When closed, the
 * segments are mapped straight through. Pure string/array math — no DOM.
 */
export function buildMirrorSegments(
  segs: PromptSegment[],
  anchorIdx: number,
  isOpen: boolean
): MirrorSegment[] {
  if (!isOpen || anchorIdx < 0) return segs.map(toMirror);
  const result: MirrorSegment[] = [];
  let charPos = 0;
  let markerInserted = false;
  for (const seg of segs) {
    const segLen = seg.value.length;
    if (!markerInserted && charPos + segLen > anchorIdx) {
      const offset = anchorIdx - charPos;
      if (seg.type === "text") {
        if (offset > 0) result.push({ type: "text", value: seg.value.slice(0, offset) });
        result.push({ type: "marker", value: "" });
        if (offset < segLen) result.push({ type: "text", value: seg.value.slice(offset) });
      } else {
        result.push({ type: "marker", value: "" });
        result.push(toMirror(seg));
      }
      markerInserted = true;
    } else if (!markerInserted && charPos + segLen === anchorIdx) {
      result.push(toMirror(seg));
      result.push({ type: "marker", value: "" });
      markerInserted = true;
    } else {
      result.push(toMirror(seg));
    }
    charPos += segLen;
  }
  if (!markerInserted) result.push({ type: "marker", value: "" });
  return result;
}
