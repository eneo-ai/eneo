// What a returned value looks like, decided the same way in the child (export), the tool
// (presentation hints) and the result view (rendering), so none of them can disagree.
// Pure: no imports, so the view bundle can take it as it is.

export type TabularForm = "records" | "matrix";
/** A value that is a table: column names and one array per row. */
export type Tabular = { form: TabularForm; columns: string[]; rows: unknown[][] };

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isHeaderCell = (value: unknown) => typeof value === "string" || typeof value === "number";

/**
 * The table a value describes, or undefined when it is not one.
 *
 * Records: a non-empty array of plain objects; the columns are the union of their keys in
 * first-seen order and a missing key is an empty cell, as model-written reducers often leave
 * optional fields out. Matrix: a non-empty array of arrays whose first row names the columns;
 * a short row is padded, a longer row makes the value non-tabular, since dropping cells
 * silently would be worse than a retry. Nested values stay as they are; the CSV writer renders
 * them as JSON text.
 */
export function asTabular(value: unknown): Tabular | undefined {
  if (!Array.isArray(value) || value.length === 0) return undefined;
  if (value.every(isPlainObject)) {
    const columns: string[] = [];
    const seen = new Set<string>();
    for (const record of value)
      for (const key of Object.keys(record))
        if (!seen.has(key)) {
          seen.add(key);
          columns.push(key);
        }
    if (columns.length === 0) return undefined;
    return {
      form: "records",
      columns,
      rows: value.map((record) => columns.map((column) => (column in record ? record[column] : null))),
    };
  }
  if (value.every(Array.isArray)) {
    const [header, ...body] = value as unknown[][];
    if (!header || header.length === 0 || !header.every(isHeaderCell)) return undefined;
    const columns = header.map(String);
    if (body.some((row) => row.length > columns.length)) return undefined;
    return {
      form: "matrix",
      columns,
      rows: body.map((row) => [...row, ...new Array<null>(columns.length - row.length).fill(null)]),
    };
  }
  return undefined;
}

/** The first `count` rows of a tabular value, in the shape the script returned them. */
export function previewRows(value: unknown[], form: TabularForm, count: number): unknown[] {
  return form === "matrix" ? value.slice(0, count + 1) : value.slice(0, count);
}

/** A short description of a value for an error message: "an array of 3 strings". */
export function describeShape(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (Array.isArray(value)) {
    if (value.length === 0) return "an empty array";
    const kinds = new Set(value.map(kindOf));
    const [kind] = kinds;
    return kinds.size === 1
      ? `an array of ${value.length} ${kind}${value.length === 1 ? "" : "s"}`
      : `an array of ${value.length} mixed values`;
  }
  if (typeof value === "object") return `an object with ${Object.keys(value).length} keys`;
  return `a ${typeof value}`;
}

function kindOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}
