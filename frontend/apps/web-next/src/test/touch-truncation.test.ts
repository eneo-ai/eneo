import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const srcDir = path.resolve(import.meta.dirname, "..");

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) return sources(file);
    return /\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name) ? [file] : [];
  });
}

/**
 * A name cut off with an ellipsis whose full text is only in a `title` attribute: a tooltip a
 * touch screen never shows, so the rest of the name cannot be read at all. On a coarse pointer
 * it wraps instead.
 */
describe("truncated text with a title", () => {
  it("wraps on a touch screen", () => {
    const faults: string[] = [];
    for (const file of sources(srcDir)) {
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, index) => {
        const truncated = /className="[^"]*\btruncate\b[^"]*"/.exec(line)?.[0];
        if (!truncated || !/\btitle=\{/.test(line)) return;
        if (!truncated.includes("pointer-coarse:whitespace-normal"))
          faults.push(`${path.relative(srcDir, file)}:${index + 1}`);
      });
    }
    expect(faults).toEqual([]);
  });
});
