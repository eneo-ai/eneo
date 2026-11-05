import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { floatingSnippet, pinnedSnippet, standaloneUrl } from "./snippet.js";
const release = { version: "1.4.2", channel: "v1", integrity: "sha384-abc" };
describe("install snippets", () => {
  it("builds the floating snippet from the channel", () => {
    assert.deepStrictEqual(
      floatingSnippet({ origin: "https://eneo.kommun.se/", publicId: "wgt_x", release }),
      '<script async src="https://eneo.kommun.se/widget/v1/eneo.js" data-widget-id="wgt_x"></script>'
    );
  });
  it("offers no snippet to paste when the loader is not built", () => {
    assert.strictEqual(
      floatingSnippet({ origin: "https://eneo.kommun.se", publicId: "wgt_x", release: null }),
      null
    );
  });
  it("pins the exact version with integrity and crossorigin", () => {
    assert.deepStrictEqual(
      pinnedSnippet({ origin: "https://eneo.kommun.se", publicId: "wgt_x", release }),
      '<script async src="https://eneo.kommun.se/widget/1.4.2/eneo.js" integrity="sha384-abc" crossorigin="anonymous" data-widget-id="wgt_x"></script>'
    );
    assert.strictEqual(
      pinnedSnippet({ origin: "https://eneo.kommun.se", publicId: "wgt_x", release: null }),
      null
    );
  });
  it("leaves the language and position to the saved settings the loader reads live", () => {
    // A snippet pasted once must follow later edits and template locks.
    const options = {
      origin: "https://eneo.kommun.se",
      publicId: "wgt_x",
      language: "en",
      position: "bottom-left",
      release
    };
    for (const snippet of [floatingSnippet(options), pinnedSnippet(options)]) {
      assert.ok(!snippet.includes("data-lang"));
      assert.ok(!snippet.includes("data-position"));
    }
  });
  it("escapes attribute values", () => {
    assert.ok(
      floatingSnippet({ origin: "https://eneo.kommun.se", publicId: 'x"y', release }).includes(
        'data-widget-id="x&quot;y"'
      )
    );
  });
  it("links the stand-alone page in the widget language", () => {
    assert.deepStrictEqual(
      standaloneUrl({ origin: "https://eneo.kommun.se", publicId: "wgt_x" }),
      "https://eneo.kommun.se/embed/wgt_x?mode=full"
    );
    assert.deepStrictEqual(
      standaloneUrl({ origin: "https://eneo.kommun.se", publicId: "wgt_x", language: "en" }),
      "https://eneo.kommun.se/en/embed/wgt_x?mode=full"
    );
  });
});
