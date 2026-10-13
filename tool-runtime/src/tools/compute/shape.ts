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

export type DisplayMode = "auto" | "result" | "none";
/** What the result view shows for a run: a table, the value itself, or nothing. */
export type ResultKind = "table" | "value" | false;

/**
 * Whether the view has something to show for a result, and what. A failed run is the model's
 * retry loop, an exported table is its own file and a hidden intermediate step stays hidden; a
 * table of several rows is the one shape prose cannot carry, so it is shown unasked, while a
 * scalar or a small object belongs in the answer unless the model asks for it to be shown.
 * The tool asks the same question to tell the model what the reader sees.
 */
export function showsResult(run: {
  ok: boolean;
  result: unknown;
  exported: boolean;
  display: DisplayMode;
}): ResultKind {
  if (!run.ok || run.display === "none") return false;
  const table = asTabular(run.result);
  if (table && table.rows.length > 1) return "table";
  return run.display === "result" ? "value" : false;
}

/**
 * A key as a label: an identifier such as `result_kr`, `interestRate` or `belopp` reads as
 * "Result kr", "Interest rate" or "Belopp". A key that is already words, or starts with a
 * capital, a digit or punctuation, is shown as it is.
 */
export function labelOf(key: string): string {
  if (!/^\p{Ll}[\p{L}\p{N}]*(?:[_-][\p{L}\p{N}]+)*$/u.test(key)) return key;
  const words = key
    .split(/[_-]/)
    .flatMap((part) => part.split(/(?<=\p{Ll}|\p{N})(?=\p{Lu})/u))
    .filter(Boolean)
    .map((word) => word.toLowerCase());
  const [first, ...rest] = words;
  if (!first) return key;
  return [first.charAt(0).toUpperCase() + first.slice(1), ...rest].join(" ");
}

export type Scalar = number | string | boolean;
/** An input the reader can edit field by field: a non-empty flat object of scalars. */
export function editableInput(input: unknown): Record<string, Scalar> | undefined {
  if (!isPlainObject(input)) return undefined;
  const entries = Object.entries(input);
  if (entries.length === 0 || entries.length > 24) return undefined;
  if (!entries.every(([, value]) => ["number", "string", "boolean"].includes(typeof value)))
    return undefined;
  return input as Record<string, Scalar>;
}
