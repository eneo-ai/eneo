import { describe, expect, it } from "vitest";
import { appSources } from "./app-sources";

/**
 * A name cut off with an ellipsis whose full text is only in a `title` attribute: a tooltip a
 * touch screen never shows, so the rest of the name cannot be read at all. On a coarse pointer
 * it wraps instead.
 */
describe("truncated text with a title", () => {
  it("wraps on a touch screen", () => {
    const faults: string[] = [];
    for (const { file, text } of appSources) {
      if (!file.endsWith(".tsx")) continue;
      text.split("\n").forEach((line, index) => {
        const truncated = /className="[^"]*\btruncate\b[^"]*"/.exec(line)?.[0];
        if (!truncated || !/\btitle=\{/.test(line)) return;
        if (!truncated.includes("pointer-coarse:whitespace-normal"))
          faults.push(`${file}:${index + 1}`);
      });
    }
    expect(faults).toEqual([]);
  });
});
