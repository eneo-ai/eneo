import { describe, expect, it } from "vitest";
import { floatingSnippet, pinnedSnippet, standaloneUrl } from "./snippet";

const release = { version: "1.4.2", channel: "v1", integrity: "sha384-abc" };

describe("install snippets", () => {
  it("builds the floating snippet from the channel", () => {
    expect(floatingSnippet({ origin: "https://eneo.kommun.se/", publicId: "wgt_x", release })).toBe(
      '<script async src="https://eneo.kommun.se/widget/v1/eneo.js" data-widget-id="wgt_x"></script>'
    );
  });

  it("offers no snippet to paste when the loader is not built", () => {
    expect(
      floatingSnippet({ origin: "https://eneo.kommun.se", publicId: "wgt_x", release: null })
    ).toBeNull();
  });

  it("pins the exact version with integrity and crossorigin", () => {
    expect(pinnedSnippet({ origin: "https://eneo.kommun.se", publicId: "wgt_x", release })).toBe(
      '<script async src="https://eneo.kommun.se/widget/1.4.2/eneo.js" integrity="sha384-abc" crossorigin="anonymous" data-widget-id="wgt_x"></script>'
    );
    expect(
      pinnedSnippet({ origin: "https://eneo.kommun.se", publicId: "wgt_x", release: null })
    ).toBeNull();
  });

  it("leaves the language and position to the saved settings the loader reads live", () => {
    // A snippet pasted once must follow later edits and template locks.
    const options = {
      origin: "https://eneo.kommun.se",
      publicId: "wgt_x",
      language: "en" as const,
      position: "bottom-left",
      release
    };
    for (const snippet of [floatingSnippet(options), pinnedSnippet(options)]) {
      expect(snippet).not.toContain("data-lang");
      expect(snippet).not.toContain("data-position");
    }
  });

  it("escapes attribute values", () => {
    expect(
      floatingSnippet({ origin: "https://eneo.kommun.se", publicId: 'x"y', release })
    ).toContain('data-widget-id="x&quot;y"');
  });

  it("links the stand-alone page in the widget language", () => {
    expect(standaloneUrl({ origin: "https://eneo.kommun.se", publicId: "wgt_x" })).toBe(
      "https://eneo.kommun.se/embed/wgt_x?mode=full"
    );
    expect(
      standaloneUrl({ origin: "https://eneo.kommun.se", publicId: "wgt_x", language: "en" })
    ).toBe("https://eneo.kommun.se/en/embed/wgt_x?mode=full");
  });
});
