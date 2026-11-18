import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const appDir = path.resolve(import.meta.dirname, "../..");
const baseline: unknown = JSON.parse(
  readFileSync(path.join(appDir, "tests/contrast-incomplete.baseline.json"), "utf8")
);

/**
 * tests/contrast-incomplete.baseline.json: per axe scan, how many nodes axe could
 * not judge for colour contrast, by axe's reason (tests/contrast-incomplete.ts).
 * The page scans compare against it; this keeps it a file they can read.
 */
describe("the contrast-incomplete baseline", () => {
  it("maps `<variant>|<screen>` to counts by reason", () => {
    expect(baseline).toBeTypeOf("object");
    expect(Array.isArray(baseline)).toBe(false);
    const malformed = Object.entries(baseline as Record<string, unknown>).filter(
      ([key, counts]) =>
        !/^[^|]+\|[^|]+$/.test(key) ||
        typeof counts !== "object" ||
        counts === null ||
        Object.keys(counts).length === 0 ||
        Object.entries(counts).some(
          ([reason, count]) =>
            !/^[a-zA-Z]+$/.test(reason) || !Number.isInteger(count) || (count as number) < 1
        )
    );
    expect(malformed).toEqual([]);
  });

  it("is sorted, as CONTRAST_UPDATE=1 writes it, so a diff shows only what changed", () => {
    const keys = Object.keys(baseline as Record<string, unknown>);
    expect(keys).toEqual([...keys].sort((a, b) => a.localeCompare(b)));
  });
});
