import fs from "node:fs";
import path from "node:path";
import type { Result } from "axe-core";

/*
 * What axe could not judge for colour contrast. axe puts text over a gradient,
 * an image or another element in `incomplete`, not `violations`, and Astryx and
 * the legacy buttons paint hover and pressed as a gradient, so that text is never
 * judged. tests/contrast-incomplete.baseline.json holds, per scan, how many such
 * places there were and why (axe's messageKey: bgImage, bgGradient, bgOverlap, …).
 * A place is a node's selector without a row's position, generated ids and the
 * attributes that hold a row's data, so the same cell in 4 rows or in 40 is one:
 * the count follows the page, not its data.
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

/**
 * A selector without what tells copies of one place apart: a row's or a list
 * item's position, generated ids (`#space-3`), and the attributes that hold a
 * row's data (`DATA_ATTRIBUTES`). Columns, components, named ids and every
 * other attribute stay, so another column or control is a place of its own.
 */
const DATA_ATTRIBUTES = /\[(?:href|src|data-row|data-id)\b[^\]]*\]/g;

function placeOf(selector: unknown): string {
  return String(selector)
    .replace(/\b(tr|li|option):nth-(?:child|of-type)\(\d+\)/g, "$1")
    .replace(DATA_ATTRIBUTES, "")
    .replace(/#(?:\\.|[\w-])*\d(?:\\.|[\w-])*/g, "");
}

/** Per reason, how many distinct places axe could not judge for contrast. */
export function incompleteCounts(incomplete: Result[]): Record<string, number> {
  const places: Record<string, Set<string>> = {};
  for (const node of incomplete.find((result) => result.id === "color-contrast")?.nodes ?? []) {
    const reason = String(node.any[0]?.data?.messageKey ?? "unknown");
    const place = JSON.stringify(node.target.map(placeOf));
    (places[reason] ??= new Set()).add(place);
  }
  return Object.fromEntries(Object.entries(places).map(([reason, set]) => [reason, set.size]));
}

/** The baseline's verdict on one scan's `incomplete` results: a problem, or nothing. */
export function contrastIncomplete(key: string, incomplete: Result[]): string[] {
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
