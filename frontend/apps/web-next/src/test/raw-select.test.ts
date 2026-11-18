import { describe, expect, it } from "vitest";
import { appSources } from "./app-sources";

/**
 * A raw <select> is not one of the design system's fields, so it carries its own
 * size: 16 px text on a phone (iPhone Safari zooms into anything smaller when it
 * takes focus, and the page stays zoomed) and 44 px tall on a touch pointer.
 * The contract's `zoom` check sees the screens that are open; this sees the dialogs.
 */
describe("raw <select> elements", () => {
  it("are 16 px on a phone and 44 px on a touch pointer", () => {
    const faults: string[] = [];
    for (const { file, text } of appSources) {
      if (!file.endsWith(".tsx")) continue;
      for (const match of text.matchAll(/<select\b/g)) {
        // The opening tag's attributes run up to the first <option> or the close tag.
        const tag = text.slice(match.index, text.indexOf("<option", match.index));
        const line = text.slice(0, match.index).split("\n").length;
        const classes = tag.match(/className="([^"]*)"/)?.[1] ?? "";
        const hasTouchHeight = classes
          .split(/\s+/)
          .some((token) => token === "min-h-11" || token === "pointer-coarse:min-h-11");
        if (!/\btext-base\b/.test(classes) || !hasTouchHeight) faults.push(`${file}:${line}`);
      }
    }
    expect(faults).toEqual([]);
  });
});
