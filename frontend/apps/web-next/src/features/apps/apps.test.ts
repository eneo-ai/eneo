import { describe, expect, it } from "vitest";
import { getResultTitle, inputFieldRules, isRunActive } from "./apps";

describe("getResultTitle", () => {
  it("prefixes text input and joins file names", () => {
    expect(
      getResultTitle({
        input: { text: "Summarize", files: [{ name: "a.pdf" }, { name: "b.pdf" }] }
      })
    ).toBe("Input: Summarize, a.pdf, b.pdf");
  });

  it("uses only file names when there is no text", () => {
    expect(getResultTitle({ input: { text: null, files: [{ name: "clip.mp3" }] } })).toBe(
      "clip.mp3"
    );
  });

  it("falls back to a placeholder when there is no input", () => {
    expect(getResultTitle({ input: { text: null, files: [] } })).toBe(
      "No input found to generate name"
    );
  });
});

describe("isRunActive", () => {
  it("is active while queued or in progress", () => {
    expect(isRunActive("queued")).toBe(true);
    expect(isRunActive("in progress")).toBe(true);
  });

  it("is inactive once complete or failed", () => {
    expect(isRunActive("complete")).toBe(false);
    expect(isRunActive("failed")).toBe(false);
  });
});

describe("inputFieldRules", () => {
  it("derives accept string, caps and per-type limits", () => {
    const rules = inputFieldRules({
      accepted_file_types: [
        { mimetype: "application/pdf", size_limit: 1000 },
        { mimetype: "text/plain", size_limit: 500 }
      ],
      limit: { max_files: 3, max_size: 5000 }
    });
    expect(rules.acceptString).toBe("application/pdf,text/plain");
    expect(rules.maxFiles).toBe(3);
    expect(rules.maxSize).toBe(5000);
    expect(rules.perTypeLimits).toEqual([
      { mimetype: "application/pdf", sizeLimit: 1000 },
      { mimetype: "text/plain", sizeLimit: 500 }
    ]);
  });

  it("treats zero limits as unbounded", () => {
    const rules = inputFieldRules({
      accepted_file_types: [],
      limit: { max_files: 0, max_size: 0 }
    });
    expect(rules.acceptString).toBe("");
    expect(rules.maxFiles).toBe(Infinity);
    expect(rules.maxSize).toBe(Infinity);
  });
});
