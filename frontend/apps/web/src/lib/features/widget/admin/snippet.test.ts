import { describe, expect, it } from "vitest";
import { floatingSnippet, pinnedSnippet, standaloneUrl } from "./snippet";

const release = { version: "1.4.2", channel: "v1", integrity: "sha384-abc" };

describe("install snippets", () => {
  it("builds the floating snippet from the channel", () => {
    expect(floatingSnippet({ origin: "https://eneo.kommun.se/", publicId: "wgt_x", release })).toBe(
      '<script async src="https://eneo.kommun.se/widget/v1/eneo.js" data-widget-id="wgt_x"></script>'
    );
  });

  it("falls back to v1 when the loader is not built and adds a fixed language", () => {
    expect(
      floatingSnippet({
        origin: "https://eneo.kommun.se",
        publicId: "wgt_x",
        language: "en",
        release: null
      })
    ).toBe(
      '<script async src="https://eneo.kommun.se/widget/v1/eneo.js" data-widget-id="wgt_x" data-lang="en"></script>'
    );
  });

  it("pins the exact version with integrity and crossorigin", () => {
    expect(pinnedSnippet({ origin: "https://eneo.kommun.se", publicId: "wgt_x", release })).toBe(
      '<script async src="https://eneo.kommun.se/widget/1.4.2/eneo.js" integrity="sha384-abc" crossorigin="anonymous" data-widget-id="wgt_x"></script>'
    );
    expect(
      pinnedSnippet({ origin: "https://eneo.kommun.se", publicId: "wgt_x", release: null })
    ).toBeNull();
  });

  it("carries the saved launcher position in both snippets", () => {
    const options = {
      origin: "https://eneo.kommun.se",
      publicId: "wgt_x",
      position: "bottom-left" as const,
      release
    };
    expect(floatingSnippet(options)).toBe(
      '<script async src="https://eneo.kommun.se/widget/v1/eneo.js" data-widget-id="wgt_x" data-position="bottom-left"></script>'
    );
    expect(pinnedSnippet(options)).toBe(
      '<script async src="https://eneo.kommun.se/widget/1.4.2/eneo.js" integrity="sha384-abc" crossorigin="anonymous" data-widget-id="wgt_x" data-position="bottom-left"></script>'
    );
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
