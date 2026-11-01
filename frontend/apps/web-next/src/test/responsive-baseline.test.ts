import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const appDir = path.resolve(import.meta.dirname, "../..");
const baseline: Record<string, string[]> = JSON.parse(
  readFileSync(path.join(appDir, "tests/responsive-contract.baseline.json"), "utf8")
);
const entries = Object.values(baseline).flat();

/**
 * How many known violations tests/responsive-contract.baseline.json may list.
 * It is empty: every screen meets the contract, so a violation fails the run and
 * is fixed, not listed. Raising this is a decision to ship a screen that is worse
 * on a phone, and shows up in review as this line.
 */
const BASELINE_BUDGET = 0;

describe("the responsive contract's baseline", () => {
  it("never grows", () => {
    expect(entries.length).toBeLessThanOrEqual(BASELINE_BUDGET);
  });

  it("is not left with room to grow back: lower the budget when the baseline shrinks", () => {
    expect(BASELINE_BUDGET - entries.length).toBeLessThan(10);
  });

  it("never excuses sideways scroll or a screen that did not open", () => {
    expect(entries.filter((entry) => /scroll|did not open/i.test(entry))).toEqual([]);
  });

  it("names only the kinds of violation the contract measures", () => {
    const measured = ["clipped", "clippedY", "outside", "overlap", "small", "zoom", "hint"];
    const kinds = new Set(entries.map((entry) => entry.split(" ")[0]));
    expect([...kinds].filter((kind) => !measured.includes(kind!))).toEqual([]);
  });
});
