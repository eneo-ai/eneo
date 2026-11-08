import fs from "node:fs";
import path from "node:path";
import type { Result } from "axe-core";

/*
 * What axe could not judge for colour contrast. axe puts text over a gradient,
 * an image or another element in `incomplete`, not `violations`, and Astryx and
 * the legacy buttons paint hover and pressed as a gradient, so that text is never
 * judged. tests/contrast-incomplete.baseline.json holds, per scan, how many such
 * places there were and why (axe's messageKey: bgImage, bgGradient, bgOverlap, …).
 * A place is a node's path from the document root (axe's `ancestry`, so scans
 * run with it on) without a row's position, so the same cell in 4 rows or in 40
 * is one and any other node is a place of its own: the count follows the page,
 * not its data.
 *
 * The baseline is a ratchet: a scan may not leave more text unjudged than its
 * entry (a missing entry is 0). CONTRAST_UPDATE=1 rewrites the entries of the
 * scans a run makes; a narrowed run (A11Y_ROUTES, A11Y_VARIANTS) touches only its own.
 *
 * A rule axe stopped on is a failure, never a count: its one error node stands in for
 * a page it did not judge, and it reports no violations either. A table that scrolls
 * sideways stops color-contrast once its middle lies below the app frame, so a stack
 * that piled up rows from an earlier run measures less than a fresh one.
 */

const BASELINE = path.resolve(process.cwd(), "tests/contrast-incomplete.baseline.json");
type Baseline = Record<string, Record<string, number>>;
const update = process.env.CONTRAST_UPDATE === "1";

function read(): Baseline {
  return fs.existsSync(BASELINE) ? JSON.parse(fs.readFileSync(BASELINE, "utf8")) : {};
}

const total = (counts: Record<string, number> = {}) =>
  Object.values(counts).reduce((sum, count) => sum + count, 0);

/** A path without a row's or a list item's position; a column keeps its own. */
const placeOf = (path: unknown) => String(path).replace(/\b(tr|li|option):nth-child\(\d+\)/g, "$1");

/** Per reason, how many distinct places axe could not judge for contrast. */
export function incompleteCounts(incomplete: Result[]): Record<string, number> {
  const places: Record<string, Set<string>> = {};
  for (const node of incomplete.find((result) => result.id === "color-contrast")?.nodes ?? []) {
    const reason = String(node.any[0]?.data?.messageKey ?? "unknown");
    const place = JSON.stringify((node.ancestry ?? node.target).map(placeOf));
    (places[reason] ??= new Set()).add(place);
  }
  return Object.fromEntries(Object.entries(places).map(([reason, set]) => [reason, set.size]));
}

/** The rules axe stopped on, each with the error it stopped on. */
const stoppedRules = (incomplete: Result[]) =>
  incomplete.flatMap((result) =>
    result.nodes.flatMap((node) =>
      node.none
        .filter((check) => check.id === "error-occurred")
        .map((check) => `axe stopped ${result.id}: ${check.data?.message}`)
    )
  );

/** The baseline's verdict on one scan's `incomplete` results: a problem, or nothing. */
export function contrastIncomplete(key: string, incomplete: Result[]): string[] {
  const stopped = stoppedRules(incomplete);
  if (stopped.length > 0) return stopped.map((problem) => `${key}: ${problem}`);
  const counts = incompleteCounts(incomplete);
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
        `${key}: axe could not judge the contrast of ${total(counts)} places, baseline ${allowed} ` +
          `(${JSON.stringify(counts)}); fix the new ones, or CONTRAST_UPDATE=1 when the change is reviewed`
      ]
    : [];
}
