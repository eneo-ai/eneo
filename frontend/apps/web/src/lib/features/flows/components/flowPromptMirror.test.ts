import { describe, it, expect } from "vitest";
import { toMirror, buildMirrorSegments } from "./flowPromptMirror";
import type { PromptSegment } from "$lib/features/flows/flowVariableTokens";

const text = (value: string): PromptSegment => ({ type: "text", value });
const variable = (value: string): PromptSegment => ({
  type: "variable",
  value,
  token: value,
  category: "field"
});

describe("toMirror", () => {
  it("maps a text segment", () => {
    expect(toMirror(text("hej"))).toEqual({ type: "text", value: "hej" });
  });

  it("maps a variable segment with its category", () => {
    expect(toMirror(variable("{{namn}}"))).toEqual({
      type: "variable",
      value: "{{namn}}",
      category: "field"
    });
  });
});

describe("buildMirrorSegments", () => {
  const segs = [text("hej "), variable("{{namn}}")];

  it("inserts no marker when the popover is closed", () => {
    const out = buildMirrorSegments(segs, 2, false);
    expect(out.some((s) => s.type === "marker")).toBe(false);
    expect(out).toHaveLength(2);
  });

  it("inserts no marker when the anchor is negative", () => {
    const out = buildMirrorSegments(segs, -1, true);
    expect(out.some((s) => s.type === "marker")).toBe(false);
  });

  it("splices a marker inside a text segment at the caret offset", () => {
    const out = buildMirrorSegments([text("hej ")], 2, true);
    expect(out).toEqual([
      { type: "text", value: "he" },
      { type: "marker", value: "" },
      { type: "text", value: "j " }
    ]);
  });

  it("places the marker before a variable when the caret sits at its start", () => {
    const out = buildMirrorSegments(segs, 4, true);
    const markerIdx = out.findIndex((s) => s.type === "marker");
    expect(markerIdx).toBe(1);
    expect(out[2]).toEqual({ type: "variable", value: "{{namn}}", category: "field" });
  });

  it("appends the marker at the end when the caret is past all segments", () => {
    const out = buildMirrorSegments([text("hej")], 10, true);
    expect(out[out.length - 1]).toEqual({ type: "marker", value: "" });
  });
});
