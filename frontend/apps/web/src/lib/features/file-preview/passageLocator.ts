import { parseTableLocator } from "./tableReference";

// A locator says which of several identical passages is meant. It is written
// in plain English because the model reads it too, as part of the quote's
// source line; these are the only shapes it takes. Shared by the DOM-based
// previews (Word, plain text, tables) and the document editor.

/** Rows of a table, as the table preview describes them. */
export const ROWS_LOCATOR =
  /^(?:sheet "(.*?)", )?rows? (\d+)(?:-\d+)? \((?:the header(?: and data rows? \d+(?:-\d+)?)?|data rows? \d+(?:-\d+)?)\)(?:, cells: .*)?$/;
/** Which of several identical passages is meant. */
export const OCCURRENCE_LOCATOR = /^occurrence (\d+) of \d+$/;

/** A rectangle of cells in one of a document's tables, counted from 1 with the header as row 1. */
export const TABLE_CELLS_LOCATOR =
  /^table (\d+), rows? (\d+)(?:-(\d+))?, columns? (\d+)(?:-(\d+))?$/;

/** More matches than this and the passage is not worth locating. */
export const MAX_MATCHES = 200;

/** Whether `text` is a locator, as opposed to the tail of a file name. */
export const isLocator = (text: string) =>
  !!parseTableLocator(text) ||
  ROWS_LOCATOR.test(text) ||
  OCCURRENCE_LOCATOR.test(text) ||
  TABLE_CELLS_LOCATOR.test(text);

const span = (first: number, last: number) => (first === last ? `${first}` : `${first}-${last}`);
const plural = (first: number, last: number) => (first === last ? "" : "s");

/** The locator for a rectangle of cells: `rows` and `columns` run from 1, both ends included. */
export const tableCellsLocator = (
  table: number,
  rows: [number, number],
  columns: [number, number]
) =>
  `table ${table}, row${plural(...rows)} ${span(...rows)}, column${plural(...columns)} ${span(...columns)}`;

/** The table and the cells a table locator points at, else null. */
export function parseTableCellsLocator(
  locator: string | null
): { table: number; rows: [number, number]; columns: [number, number] } | null {
  const match = locator ? TABLE_CELLS_LOCATOR.exec(locator) : null;
  if (!match) return null;
  const [, table, firstRow, lastRow, firstColumn, lastColumn] = match;
  return {
    table: Number(table),
    rows: [Number(firstRow), Number(lastRow ?? firstRow)],
    columns: [Number(firstColumn), Number(lastColumn ?? firstColumn)]
  };
}

/** The sheet a locator points into, when it names one. */
export const locatorSheet = (locator: string | null) =>
  parseTableLocator(locator)?.sheet ?? ((locator && ROWS_LOCATOR.exec(locator)?.[1]) || null);

/**
 * A passage as it is matched against content: without the cut mark a long
 * quote ends in, and without whitespace, since a selection reports line
 * breaks and tabs between blocks and cells that the text itself does not hold.
 */
export const stripForMatch = (text: string) => text.replace(/…$/, "").replace(/\s+/g, "");

/** The locator for the `index`th (from 1) of `total` identical passages. */
export const occurrenceLocator = (index: number, total: number) =>
  `occurrence ${index} of ${total}`;

/** The occurrence (from 1) an occurrence locator points at, else null. */
export const occurrenceIndex = (locator: string | null) => {
  const match = locator ? OCCURRENCE_LOCATOR.exec(locator) : null;
  return match ? Number(match[1]) : null;
};
