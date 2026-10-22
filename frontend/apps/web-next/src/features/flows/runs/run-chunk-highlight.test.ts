import { describe, expect, it } from "vitest";
import { highlightSegments, relevanceLevel } from "./run-chunk-highlight";

describe("highlightSegments", () => {
  it("cuts the document into plain and highlighted pieces, overlaps included", () => {
    const { segments, found } = highlightSegments("Ett två tre fyra fem", [
      " två tre ",
      "tre fyra",
      "saknas"
    ]);

    expect(segments).toEqual([
      { text: "Ett ", passages: [], starts: [] },
      { text: "två ", passages: [0], starts: [0] },
      { text: "tre", passages: [0, 1], starts: [1] },
      { text: " fyra", passages: [1], starts: [] },
      { text: " fem", passages: [], starts: [] }
    ]);
    expect(found).toEqual([true, true, false]);
  });

  it("leaves a document without matches as one plain piece", () => {
    expect(highlightSegments("Text", []).segments).toEqual([
      { text: "Text", passages: [], starts: [] }
    ]);
  });
});

describe("relevanceLevel", () => {
  it("names a score high, moderate or low", () => {
    expect(relevanceLevel(0.72)).toBe("high");
    expect(relevanceLevel(0.31)).toBe("moderate");
    expect(relevanceLevel(-0.1)).toBe("low");
  });
});
