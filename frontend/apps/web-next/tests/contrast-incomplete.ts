import fs from "node:fs";
import path from "node:path";
import type { Result } from "axe-core";

/*
 * What axe could not judge for colour contrast. axe puts text over a gradient,
 * an image or another element in `incomplete`, not `violations`, and Astryx and
 * the legacy buttons paint hover and pressed as a gradient, so that text is never
 * judged. tests/contrast-incomplete.baseline.json holds, per scan, how many such
 * nodes there were and why (axe's messageKey: bgImage, bgGradient, bgOverlap, …).
 *
 * The baseline is a ratchet: a scan may not leave more text unjudged than its
 * entry (a missing entry is 0). CONTRAST_UPDATE=1 rewrites the entries of the
 * scans a run makes; a narrowed run (A11Y_ROUTES, A11Y_VARIANTS) touches only its own.
 */

const BASELINE = path.resolve(process.cwd(), "tests/contrast-incomplete.baseline.json");
type Baseline = Record<string, Record<string, number>>;
const update = process.env.CONTRAST_UPDATE === "1";

function read(): Baseline {
  return fs.existsSync(BASELINE) ? JSON.parse(fs.readFileSync(BASELINE, "utf8")) : {};
}

const total = (counts: Record<string, number> = {}) =>
  Object.values(counts).reduce((sum, count) => sum + count, 0);

/** The baseline's verdict on one scan's `incomplete` results: a problem, or nothing. */
export function contrastIncomplete(key: string, incomplete: Result[]): string[] {
  const counts: Record<string, number> = {};
  for (const node of incomplete.find((result) => result.id === "color-contrast")?.nodes ?? []) {
    const reason = String(node.any[0]?.data?.messageKey ?? "unknown");
    counts[reason] = (counts[reason] ?? 0) + 1;
  }
  const baseline = read();
  if (update) {
    // workers: 1 (playwright.config.ts), so read-merge-write cannot interleave.
    if (total(counts) > 0) baseline[key] = Object.fromEntries(Object.entries(counts).sort());
    else delete baseline[key];
    const sorted = Object.fromEntries(
      Object.entries(baseline).sort(([a], [b]) => a.localeCompare(b))
    );
    fs.writeFileSync(BASELINE, JSON.stringify(sorted, null, 1) + "\n");
    return [];
  }
  const allowed = total(baseline[key]);
  return total(counts) > allowed
    ? [
        `${key}: axe could not judge the contrast of ${total(counts)} nodes, baseline ${allowed} ` +
          `(${JSON.stringify(counts)}); fix the new ones, or CONTRAST_UPDATE=1 when the change is reviewed`
      ]
    : [];
}
