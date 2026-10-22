// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { selectedSpans, type LineText } from "./transcript-selection";

function render(html: string) {
  const container = document.createElement("div");
  container.innerHTML = html;
  document.body.append(container);
  return container;
}

afterEach(() => {
  document.body.innerHTML = "";
});

/** A range from `start` characters into the first text node to `end` into the last one. */
function rangeIn(first: Node, start: number, last: Node, end: number): Range {
  const range = document.createRange();
  range.setStart(first, start);
  range.setEnd(last, end);
  return range;
}

const text = (container: Element, selector: string) =>
  container.querySelector(selector)!.firstChild!;

describe("selectedSpans", () => {
  const raw: Record<number, LineText> = {
    0: { raw: "Hej och välkomna.", occurrences: [] },
    1: {
      raw: "Tack Sugary.",
      occurrences: [
        { segment_index: 1, char_start: 5, char_end: 11, original: "Sugary", corrected: "Çagri" }
      ]
    }
  };

  it("reads marked text in a line as a span of its raw text, without the spaces at its ends", () => {
    const container = render(
      `<p><span data-part-of="0" data-shown-start="0">Hej och välkomna.</span></p>`
    );
    const node = text(container, "[data-part-of]");
    expect(
      selectedSpans(container, rangeIn(node, 3, node, 8), (index) => raw[index] ?? null)
    ).toEqual([{ segmentIndex: 0, start: 4, end: 7 }]);
  });

  it("maps marked text across lines back through each line's corrections", () => {
    const container = render(
      `<ol>
        <li><span data-part-of="0" data-shown-start="0">Hej och välkomna.</span></li>
        <li><span data-part-of="1" data-shown-start="0">Tack Çagri.</span></li>
      </ol>`
    );
    const [first, second] = [...container.querySelectorAll("[data-part-of]")].map(
      (element) => element.firstChild!
    );
    // From "välkomna." into the middle of the corrected name.
    const spans = selectedSpans(
      container,
      rangeIn(first!, 8, second!, 7),
      (index) => raw[index] ?? null
    );
    expect(spans).toEqual([
      { segmentIndex: 0, start: 8, end: 17 },
      // Inside a corrected span the whole original is taken.
      { segmentIndex: 1, start: 0, end: 11 }
    ]);
  });

  it("reads a part that starts inside its line, and words split in their own elements", () => {
    const container = render(
      `<p><span data-part-of="0" data-shown-start="8"><span>välk</span><span>omna.</span></span></p>`
    );
    const words = container.querySelectorAll("[data-part-of] span");
    const spans = selectedSpans(
      container,
      rangeIn(words[0]!.firstChild!, 0, words[1]!.firstChild!, 2),
      (index) => raw[index] ?? null
    );
    expect(spans).toEqual([{ segmentIndex: 0, start: 8, end: 14 }]);
  });

  it("leaves out text outside the parts and lines it cannot read", () => {
    const container = render(
      `<p><b>Anna:</b> <span data-part-of="7" data-shown-start="0">Okänd rad.</span></p>`
    );
    const label = container.querySelector("b")!.firstChild!;
    const range = rangeIn(label, 0, label, 4);
    expect(selectedSpans(container, range, (index) => raw[index] ?? null)).toEqual([]);
    const part = text(container, "[data-part-of]");
    expect(
      selectedSpans(container, rangeIn(part, 0, part, 5), (index) => raw[index] ?? null)
    ).toEqual([]);
  });
});
