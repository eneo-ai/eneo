import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const appDir = path.resolve(import.meta.dirname, "../..");

/**
 * The UI probes (tests/ui-probes.ts) and the kinds of finding each one makes. Each probe holds
 * its known findings in tests/<probe>-probe.baseline.json, `<variant>|<screen>` → keys.
 */
const PROBES: Record<string, string[]> = {
  contrast: ["text", "placeholder", "boundary", "icon"],
  selected: ["pressed"],
  "left-edge": ["heading", "row", "column"]
};

/**
 * How many known findings each baseline may list. They are empty: every screen passes, so a
 * finding fails the run and is fixed, not listed. Raising this is a decision to ship a screen
 * that is harder to read or that moves its edge, and shows up in review as this line.
 */
const BASELINE_BUDGET = 0;

describe.each(Object.entries(PROBES))("the %s probe's baseline", (probe, measured) => {
  const baseline: Record<string, string[]> = JSON.parse(
    readFileSync(path.join(appDir, `tests/${probe}-probe.baseline.json`), "utf8")
  );
  const entries = Object.values(baseline).flat();

  it("never grows", () => {
    expect(entries.length).toBeLessThanOrEqual(BASELINE_BUDGET);
  });

  it("is not left with room to grow back: lower the budget when the baseline shrinks", () => {
    expect(BASELINE_BUDGET - entries.length).toBeLessThan(10);
  });

  it("names only the kinds of finding the probe makes, in a state or at rest", () => {
    const kinds = new Set(entries.map((entry) => entry.split(" ")[0]!.split(":")[0]!));
    expect([...kinds].filter((kind) => !measured.includes(kind))).toEqual([]);
  });

  it("is sorted, as PROBES_UPDATE=1 writes it, so a diff shows only what changed", () => {
    const keys = Object.keys(baseline);
    expect(keys).toEqual([...keys].sort((a, b) => a.localeCompare(b)));
    expect(keys.filter((key) => !/^[^|]+\|[^|]+$/.test(key))).toEqual([]);
  });
});
