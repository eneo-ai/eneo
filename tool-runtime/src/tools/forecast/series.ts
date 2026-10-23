// Runs inside sandbox children only: turns two columns of a source into one daily series.
import { ToolError } from "../../errors";
import type { Cell } from "../documents/ports";

export const DAY_MS = 86_400_000;

/** One value per day from `from`, in order; `null` is a day without a value. */
export type DailySeries = { from: string; values: (number | null)[] };

export function isoDay(time: number): string {
  return new Date(time).toISOString().slice(0, 10);
}

/**
 * The model reads positions, not dates, so the dates must be exactly one per day: every gap
 * would silently shift the weekly pattern. The rows are refused, never repaired, because only
 * the person who knows the data can say whether a missing day means zero or unknown.
 */
export function dailySeries(rows: Cell[][], dateAt: number, valueAt: number): DailySeries {
  let previous: number | undefined;
  const values: (number | null)[] = [];
  let from = "";
  for (const [index, row] of rows.entries()) {
    // Rows as the reader counts them in the file, with the header as row 1.
    const line = index + 2;
    const time = dayOf(row[dateAt] ?? null, line);
    if (previous !== undefined && time <= previous)
      throw new ToolError(
        "UNORDERED_DATES",
        `Row ${line}: ${isoDay(time)} comes after ${isoDay(previous)}. ` +
          "Dates must be in ascending order with each day once; sort or aggregate the rows with query_table.",
      );
    if (previous !== undefined && time > previous + DAY_MS)
      throw new ToolError(
        "MISSING_DATES",
        `The dates ${isoDay(previous + DAY_MS)} to ${isoDay(time - DAY_MS)} are missing. ` +
          "A forecast needs one row per day: use query_table to produce every day in the range " +
          "(0 where no activity means zero, an empty value where the value is unknown) and pass its export.",
      );
    if (previous === undefined) from = isoDay(time);
    previous = time;
    values.push(valueOf(row[valueAt] ?? null, line));
  }
  return { from, values };
}

const NUMBER = /^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$/;
/** The model reads single precision: a larger value would reach it as unknown. */
const LARGEST = 3.4028234663852886e38;

/**
 * A value as the file holds it. An empty cell is a day without a value; anything else must be
 * a number, because a formula error or a note in the cell is not the same as "unknown".
 */
function valueOf(cell: Cell, row: number): number | null {
  if (cell === null || cell === undefined) return null;
  const text = String(cell).trim();
  if (text === "") return null;
  const value = typeof cell === "number" ? cell : NUMBER.test(text) ? Number(text) : NaN;
  if (Number.isFinite(value) && Math.abs(value) <= LARGEST) return value;
  if (NUMBER.test(text) || typeof cell === "number")
    throw new ToolError(
      "INVALID_VALUES",
      `Row ${row}: "${text.slice(0, 40)}" is too large to forecast. Check the value in the file.`,
    );
  const comma = /^[-+]?\d+,\d+$/.test(text);
  throw new ToolError(
    "INVALID_VALUES",
    `Row ${row}: "${text.slice(0, 40)}" is not a number.` +
      (comma
        ? " It uses a decimal comma; convert the column to numbers with query_table first."
        : " Leave a cell empty when the value is unknown, or fix the value in the file."),
  );
}

/**
 * A calendar day as UTC midnight. A CSV or XLSX date arrives as `YYYY-MM-DD` (sources.ts); a
 * system export that writes each day as midnight (`2026-01-01 00:00:00`) is the same day.
 */
function dayOf(cell: Cell, row: number): number {
  const text = String(cell ?? "").trim();
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ]00:00(?::00(?:\.0+)?)?(?:Z|[+-]00:?00)?)?$/.exec(text);
  const time = match ? Date.UTC(+match[1]!, +match[2]! - 1, +match[3]!) : NaN;
  if (match && isoDay(time) === text.slice(0, 10)) return time;
  const timed = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(text);
  throw new ToolError(
    "INVALID_DATES",
    `Row ${row}: "${text.slice(0, 40)}" is not a date (YYYY-MM-DD).` +
      (timed
        ? " The values have a time of day; a forecast needs one value per day, so aggregate per day with query_table first."
        : " Choose the column that holds the dates."),
  );
}
