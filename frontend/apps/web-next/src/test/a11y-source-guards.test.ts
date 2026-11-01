import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const appDir = path.resolve(import.meta.dirname, "../..");
const srcDir = path.join(appDir, "src");

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) return sources(file);
    return /\.(tsx?|css)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [file] : [];
  });
}

/** Where a pattern occurs in the app's own source (tests excluded), as `path:line`. */
function occurrences(pattern: RegExp): string[] {
  return sources(srcDir).flatMap((file) => {
    const text = readFileSync(file, "utf8");
    return [...text.matchAll(pattern)].map(
      (match) => `${path.relative(appDir, file)}:${text.slice(0, match.index).split("\n").length}`
    );
  });
}

/**
 * Source-level guards for criteria no screen walk can reach: something the app must never do,
 * which one line of source would break (ACCESSIBILITY.md, WCAG 2.2 A/AA).
 */
describe("accessibility source guards", () => {
  it("never locks the screen's orientation (1.3.4)", () => {
    const manifest = JSON.parse(readFileSync(path.join(appDir, "public/manifest.json"), "utf8"));
    expect(manifest).not.toHaveProperty("orientation");
    expect(occurrences(/screen\.orientation\.lock|@media[^{]*\(\s*orientation/g)).toEqual([]);
  });

  it("never starts audio or video by itself (1.4.2)", () => {
    expect(occurrences(/\bautoPlay\b|\bautoplay\b/g)).toEqual([]);
  });

  it("never takes the browser's own paste or copy of a password away (3.3.8)", () => {
    // A password field that refuses paste locks out a password manager.
    expect(
      occurrences(/type=["']password["'][^>]*\bonPaste\b|\bonPaste\b[^>]*type=["']password["']/g)
    ).toEqual([]);
  });
});
