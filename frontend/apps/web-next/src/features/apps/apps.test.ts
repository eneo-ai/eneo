import { describe, expect, it } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { getResultTitle, isRunActive, spaceApps } from "./apps";

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

describe("spaceApps", () => {
  it("sorts by name with the collator it is given (å, ä, ö after z in Swedish)", () => {
    const space = makeSpace({
      apps: ["Översätt", "Avtal", "Ärendestöd", "Zon"].map((name, index) => ({
        id: `app-${index}`,
        name
      }))
    });
    const names = (compare: Intl.Collator["compare"]) =>
      spaceApps(space, compare).map((app) => app.name);

    expect(names(new Intl.Collator("sv").compare)).toEqual([
      "Avtal",
      "Zon",
      "Ärendestöd",
      "Översätt"
    ]);
    expect(names(new Intl.Collator("en").compare)).toEqual([
      "Ärendestöd",
      "Avtal",
      "Översätt",
      "Zon"
    ]);
  });
});
