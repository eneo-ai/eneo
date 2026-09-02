// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { buildOffsetMap } from "./transcriptRuns";
import { selectionToSpans, type SegmentGeometry } from "./transcriptSelection";

type PartSpec = { segmentIndex: number; displayStart: number; text: string };
type TurnSpec = { speaker: string; parts: PartSpec[] };

/** Builds the turn DOM shape the view renders: gutter + part spans. */
function buildList(turns: TurnSpec[]): HTMLElement {
  const list = document.createElement("div");
  for (const turn of turns) {
    const block = document.createElement("div");
    const gutter = document.createElement("span");
    gutter.textContent = turn.speaker;
    block.appendChild(gutter);
    const paragraph = document.createElement("p");
    for (const part of turn.parts) {
      const span = document.createElement("span");
      span.dataset.runText = "";
      span.dataset.segmentIndex = String(part.segmentIndex);
      span.dataset.displayStart = String(part.displayStart);
      span.textContent = part.text;
      paragraph.appendChild(span);
      paragraph.appendChild(document.createTextNode(" "));
    }
    block.appendChild(paragraph);
    list.appendChild(block);
  }
  document.body.appendChild(list);
  return list;
}

function identityGeometry(texts: Record<number, string>) {
  return (segmentIndex: number): SegmentGeometry | null => {
    const rawText = texts[segmentIndex];
    if (rawText === undefined) return null;
    const map = buildOffsetMap(rawText, []);
    return { rawText, displayLength: rawText.length, displayToRaw: map.displayToRaw };
  };
}

function partText(list: HTMLElement, segmentIndex: number, nth = 0): Text {
  const spans = list.querySelectorAll(`[data-segment-index="${segmentIndex}"]`);
  return spans[nth].firstChild as Text;
}

describe("selectionToSpans over the turn DOM", () => {
  it("maps a selection inside one part, trimming whitespace", () => {
    const list = buildList([
      {
        speaker: "SPEAKER_00",
        parts: [{ segmentIndex: 0, displayStart: 0, text: "Vi frågade sugary om planen." }]
      }
    ]);
    const range = document.createRange();
    range.setStart(partText(list, 0), 11);
    range.setEnd(partText(list, 0), 18);

    expect(
      selectionToSpans(list, range, identityGeometry({ 0: "Vi frågade sugary om planen." }))
    ).toEqual([{ segmentIndex: 0, charStart: 11, charEnd: 17 }]);
    list.remove();
  });

  it("maps a selection across parts of two segments in one turn", () => {
    const list = buildList([
      {
        speaker: "SPEAKER_00",
        parts: [
          { segmentIndex: 0, displayStart: 0, text: "Hej där." },
          { segmentIndex: 1, displayStart: 0, text: "Vad bra." }
        ]
      }
    ]);
    const range = document.createRange();
    range.setStart(partText(list, 0), 4);
    range.setEnd(partText(list, 1), 3);

    expect(
      selectionToSpans(list, range, identityGeometry({ 0: "Hej där.", 1: "Vad bra." }))
    ).toEqual([
      { segmentIndex: 0, charStart: 4, charEnd: 8 },
      { segmentIndex: 1, charStart: 0, charEnd: 3 }
    ]);
    list.remove();
  });

  it("maps a selection across two turns", () => {
    const list = buildList([
      { speaker: "SPEAKER_00", parts: [{ segmentIndex: 0, displayStart: 0, text: "Hej där." }] },
      { speaker: "SPEAKER_01", parts: [{ segmentIndex: 1, displayStart: 0, text: "Precis så." }] }
    ]);
    const range = document.createRange();
    range.setStart(partText(list, 0), 4);
    range.setEnd(partText(list, 1), 6);

    expect(
      selectionToSpans(list, range, identityGeometry({ 0: "Hej där.", 1: "Precis så." }))
    ).toEqual([
      { segmentIndex: 0, charStart: 4, charEnd: 8 },
      { segmentIndex: 1, charStart: 0, charEnd: 6 }
    ]);
    list.remove();
  });

  it("snaps a boundary on the gutter to the following part", () => {
    const list = buildList([
      { speaker: "SPEAKER_00", parts: [{ segmentIndex: 0, displayStart: 0, text: "Hej där." }] }
    ]);
    const gutterText = list.querySelector("span")!.firstChild as Text;
    const range = document.createRange();
    range.setStart(gutterText, 2);
    range.setEnd(partText(list, 0), 3);

    expect(selectionToSpans(list, range, identityGeometry({ 0: "Hej där." }))).toEqual([
      { segmentIndex: 0, charStart: 0, charEnd: 3 }
    ]);
    list.remove();
  });

  it("respects display-start offsets for split-segment parts", () => {
    // Segment 0 is split: this turn holds only its tail slice.
    const list = buildList([
      { speaker: "SPEAKER_01", parts: [{ segmentIndex: 0, displayStart: 9, text: "Vad bra." }] }
    ]);
    const range = document.createRange();
    range.setStart(partText(list, 0), 0);
    range.setEnd(partText(list, 0), 3);

    expect(selectionToSpans(list, range, identityGeometry({ 0: "Hej där. Vad bra." }))).toEqual([
      { segmentIndex: 0, charStart: 9, charEnd: 12 }
    ]);
    list.remove();
  });

  it("maps display offsets through corrections into raw space", () => {
    const rawText = "Vi frågade sugary om planen.";
    const corrected = "Vi frågade Çagri om planen.";
    const list = buildList([
      { speaker: "SPEAKER_00", parts: [{ segmentIndex: 0, displayStart: 0, text: corrected }] }
    ]);
    const map = buildOffsetMap(rawText, [
      { segment_index: 0, char_start: 11, char_end: 17, original: "sugary", corrected: "Çagri" }
    ]);
    const geometry = (): SegmentGeometry => ({
      rawText,
      displayLength: corrected.length,
      displayToRaw: map.displayToRaw
    });
    const range = document.createRange();
    range.setStart(partText(list, 0), 11);
    range.setEnd(partText(list, 0), 19);

    expect(selectionToSpans(list, range, geometry)).toEqual([
      { segmentIndex: 0, charStart: 11, charEnd: 20 }
    ]);
    list.remove();
  });

  it("returns nothing for selections outside the transcript", () => {
    const list = buildList([
      { speaker: "SPEAKER_00", parts: [{ segmentIndex: 0, displayStart: 0, text: "Hej där." }] }
    ]);
    const outside = document.createElement("p");
    outside.textContent = "utanför";
    document.body.appendChild(outside);
    const range = document.createRange();
    range.setStart(outside.firstChild as Text, 0);
    range.setEnd(outside.firstChild as Text, 3);

    expect(selectionToSpans(list, range, identityGeometry({ 0: "Hej där." }))).toEqual([]);
    outside.remove();
    list.remove();
  });
});
