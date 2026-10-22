/**
 * The coverage record of a step that read long material in parts
 * (`long_material` on the run step API, `LongMaterialCoverage` in
 * `long_material.py`): what was read, what was left out and why. Pure and
 * unit-tested.
 */
import type { Schema } from "@/lib/api/models";

export type LongMaterialCoverage = Schema<"LongMaterialCoverage">;
export type LongMaterialSource = Schema<"LongMaterialSourceCoverage">;

/** "1-3, 5" for segments 1, 2, 3 and 5. */
export function segmentRanges(segments: readonly number[]): string {
  const sorted = [...new Set(segments)].sort((a, b) => a - b);
  const ranges: string[] = [];
  let start: number | null = null;
  let previous: number | null = null;
  for (const segment of sorted) {
    if (start === null || previous === null || segment !== previous + 1) {
      if (start !== null && previous !== null) {
        ranges.push(start === previous ? `${start}` : `${start}-${previous}`);
      }
      start = segment;
    }
    previous = segment;
  }
  if (start !== null && previous !== null) {
    ranges.push(start === previous ? `${start}` : `${start}-${previous}`);
  }
  return ranges.join(", ");
}

/** The segments of a source whose notes did not reach the answer: failed, cut or never sent. */
export function missingSegments(source: LongMaterialSource): number[] {
  return [
    ...new Set([
      ...(source.segments_failed ?? []),
      ...(source.segments_cut ?? []),
      ...(source.segments_not_read ?? [])
    ])
  ].sort((a, b) => a - b);
}

export type LeftOutSource = {
  key: string;
  title: string;
  /** "1-3, 5", or null when every segment was read but its notes did not fit the answer. */
  segments: string | null;
  planned: number;
};

export function leftOutSources(coverage: LongMaterialCoverage): LeftOutSource[] {
  return coverage.sources
    .filter((source) => !source.complete)
    .map((source) => {
      const missing = missingSegments(source);
      return {
        key: source.key,
        title: source.title,
        segments: missing.length > 0 ? segmentRanges(missing) : null,
        planned: source.segments_planned
      };
    });
}

export function segmentCounts(coverage: LongMaterialCoverage): { read: number; planned: number } {
  return {
    read: coverage.sources.reduce((sum, source) => sum + source.segments_read.length, 0),
    planned: coverage.sources.reduce((sum, source) => sum + source.segments_planned, 0)
  };
}

/** The message key slug of a reason the core records (`"notes cut short"` → `notes_cut_short`). */
export function reasonSlug(reason: string): string {
  return reason.trim().toLowerCase().replace(/\s+/g, "_");
}
