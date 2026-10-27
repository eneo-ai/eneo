/**
 * JSON as a table source. Runs inside sandbox children only (trusted ingest lane).
 *
 * A JSON file is read by DuckDB's JSON reader and its arrays of records are written as sheet
 * CSVs, so the query lane, the column profiles and the table view treat it like a workbook.
 * Nested objects become dotted columns ("addr.city"); arrays and objects below the flattening
 * depth stay as JSON text, which DuckDB's json functions read in a query. The file's inferred
 * structure is kept so inspect_table can describe the tree, and query_json reads a value at a
 * path from the same file.
 */
import { DuckDBInstance, type DuckDBConnection } from "@duckdb/node-api";
import { ToolError } from "../../../errors";
import { spillDirectory } from "./duckdb";

/** What inspect_table says about a JSON file beyond its sheets. */
export type JsonSummary = {
  /** OBJECT, ARRAY or a scalar type; "RECORDS" for newline-delimited or concatenated values. */
  root_type: string;
  /** Top-level values in the file: 1 for an ordinary document, one per line for JSON Lines. */
  values: number;
  /** DuckDB's inferred structure of the whole file (types in place of values), bounded. */
  structure: string;
  structure_truncated: boolean;
};

export type JsonSheetCsv = {
  name: string;
  json_path: string;
  csv: Buffer;
};

/** Deepest object nesting flattened to dotted columns; deeper values stay JSON text. */
const FLATTEN_DEPTH = 4;
/** Columns one sheet may hold; the rest of the record stays in a single JSON column. */
const MAX_COLUMNS = 200;
/** How deep in the tree arrays of records are looked for. */
const SEARCH_DEPTH = 3;
const MAX_STRUCTURE_CHARS = 6_000;
/** The column holding each element of an array of scalars or mixed values. */
const VALUE_COLUMN = "value";
/** The column holding what is left of a record once MAX_COLUMNS is reached. */
const REST_COLUMN = "_rest";

type Structure = string | Structure[] | { [key: string]: Structure };

function quoteSqlString(value: string): string {
  return "'" + value.replaceAll("'", "''") + "'";
}
function quoteIdent(name: string): string {
  return '"' + name.replaceAll('"', '""') + '"';
}
/** One JSONPath step for an object key, quoted so dots and brackets in the key are literal. */
function pathKey(key: string): string {
  return '."' + key.replaceAll("\\", "\\\\").replaceAll('"', '\\"') + '"';
}

/**
 * DuckDB memory per byte of JSON text. The reader buffers the whole value, and every json
 * function parses the whole document again while a sheet is written; measured at about 24
 * bytes per byte on documents of 8 to 20 MB.
 */
const MEMORY_BYTES_PER_INPUT_BYTE = 32;

/** An instance for one file: the configured limit, or more when the file needs it. */
async function openInstance(
  memoryMb: number,
  inputBytes: number,
): Promise<DuckDBInstance> {
  const limitMb = Math.max(
    memoryMb,
    Math.ceil((inputBytes * MEMORY_BYTES_PER_INPUT_BYTE) / 1_048_576),
  );
  return DuckDBInstance.create(":memory:", {
    memory_limit: `${limitMb}MB`,
    temp_directory: spillDirectory(),
    max_temp_directory_size: `${limitMb}MB`,
    threads: "1",
    allow_community_extensions: "false",
    autoinstall_known_extensions: "false",
    autoload_known_extensions: "false",
  });
}

/**
 * Loads the file into `src` (one row per top-level JSON value) and returns the row count.
 * `read_json_objects` keeps every value as JSON text. `read_json` would infer a nested record
 * type for the document and materialise one vector per field, which for a document with
 * thousands of distinct keys costs hundreds of MB however small the file is.
 */
async function loadSource(
  conn: DuckDBConnection,
  inputPath: string,
  inputBytes: number,
): Promise<number> {
  // One value can be the whole file; the reader refuses values above this size.
  const objectCap = Math.max(inputBytes + 1024, 1_048_576);
  try {
    await conn.run(
      `CREATE TEMPORARY TABLE src AS SELECT json FROM read_json_objects(${quoteSqlString(inputPath)}, format = 'unstructured', maximum_object_size = ${objectCap})`,
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "";
    // Only a parse error is the file's fault. Anything else (memory, I/O) is the runtime's
    // and must not be reported as invalid JSON.
    if (!message.includes("Malformed JSON")) throw error;
    const at = /at byte (\d+)/.exec(message);
    throw new ToolError(
      "INVALID_FILE",
      at
        ? `The file is not valid JSON (error near byte ${at[1]}).`
        : "The file is not valid JSON.",
    );
  }
  const count = await conn.runAndReadAll(`SELECT COUNT(*) FROM src`);
  return Number(count.getRowsJS()[0]?.[0] ?? 0);
}

function parseStructure(text: string): Structure {
  try {
    return JSON.parse(text) as Structure;
  } catch {
    return "JSON";
  }
}
const isObject = (s: Structure): s is { [key: string]: Structure } =>
  typeof s === "object" && s !== null && !Array.isArray(s);

/**
 * Where the records are. Every array found within SEARCH_DEPTH levels of the root becomes a
 * sheet named by its path; a root that is itself an array is the single sheet "records", and
 * a document without arrays is one record. Breadth first, so top-level lists come first.
 */
type SheetPlan = {
  json_path: string;
  name: string;
  /** The structure of one record. */
  element: Structure;
  /** An array gives one row per element; a record is the single object at the path. */
  kind: "array" | "record";
};
function findSheets(root: Structure, maxSheets: number): SheetPlan[] {
  if (Array.isArray(root))
    return [
      {
        json_path: "$",
        name: "records",
        element: root[0] ?? "JSON",
        kind: "array",
      },
    ];
  if (!isObject(root))
    return [
      { json_path: "$", name: "records", element: "JSON", kind: "record" },
    ];
  const found: SheetPlan[] = [];
  let level: Array<{
    path: string;
    name: string;
    node: { [key: string]: Structure };
  }> = [{ path: "$", name: "", node: root }];
  for (let depth = 0; depth < SEARCH_DEPTH && level.length; depth++) {
    const next: typeof level = [];
    for (const { path, name, node } of level)
      for (const [key, value] of Object.entries(node)) {
        const childPath = path + pathKey(key);
        const childName = name ? `${name}.${key}` : key;
        if (Array.isArray(value)) {
          // An array whose structure is empty held no elements anywhere in the file.
          if (value.length && found.length < maxSheets)
            found.push({
              json_path: childPath,
              name: childName,
              element: value[0]!,
              kind: "array",
            });
        } else if (isObject(value))
          next.push({ path: childPath, name: childName, node: value });
      }
    level = next;
  }
  if (!found.length)
    found.push({
      json_path: "$",
      name: "records",
      element: root,
      kind: "record",
    });
  // Two keys may flatten to the same name ("a.b" next to a: {b}); keep names unique.
  const seen = new Map<string, number>();
  for (const sheet of found) {
    const n = seen.get(sheet.name) ?? 0;
    seen.set(sheet.name, n + 1);
    if (n) sheet.name = `${sheet.name} (${n + 1})`;
  }
  return found;
}

/** A sheet column: the JSONPath of the field in the record, read as text or as JSON. */
type Column = { name: string; path: string; text: boolean };

/**
 * The columns of one record: scalar fields read as text, nested objects flattened to dotted
 * columns down to FLATTEN_DEPTH, arrays and deeper objects kept as JSON text. Beyond
 * MAX_COLUMNS the remaining fields are not expanded.
 */
function recordColumns(element: Structure): Column[] {
  if (!isObject(element))
    return [{ name: VALUE_COLUMN, path: "$", text: true }];
  const columns: Column[] = [];
  let overflow = false;
  const walk = (
    node: { [key: string]: Structure },
    prefix: string,
    path: string,
    depth: number,
  ) => {
    for (const [key, value] of Object.entries(node)) {
      if (columns.length >= MAX_COLUMNS - 1) {
        overflow = true;
        return;
      }
      const name = prefix ? `${prefix}.${key}` : key;
      const childPath = path + pathKey(key);
      if (isObject(value) && depth < FLATTEN_DEPTH && Object.keys(value).length)
        walk(value, name, childPath, depth + 1);
      else {
        const text = !(
          isObject(value) ||
          Array.isArray(value) ||
          value === "JSON"
        );
        columns.push({ name, path: childPath, text });
      }
    }
  };
  walk(element, "", "$", 0);
  if (overflow) columns.push({ name: REST_COLUMN, path: "$", text: false });
  return columns;
}

/**
 * The SELECT that writes the sheet from `rows` (one `rec` per row). A JSON function parses
 * its whole input on every call, so the columns are extracted with one list-valued call for
 * the text columns and one for the JSON columns: two parses per record, not one per column.
 */
function sheetSelect(columns: Column[], rows: string): string {
  const paths =
    "[" + columns.map((c) => quoteSqlString(c.path)).join(", ") + "]";
  const select = columns
    .map((c, i) => `${c.text ? "t" : "j"}[${i + 1}] AS ${quoteIdent(c.name)}`)
    .join(", ");
  return `SELECT ${select} FROM (SELECT rec->>${paths} AS t, rec->${paths} AS j FROM (${rows}))`;
}

export type JsonIngestResult = {
  sheets: JsonSheetCsv[];
  summary: JsonSummary;
};

/**
 * Reads a JSON or JSON Lines file and writes its records as sheet CSVs into `outputDir`.
 * CSV bytes are returned in memory like the workbook converter's, bounded by the caller.
 */
export async function convertJsonToCsvSheets(
  inputPath: string,
  options: { maxSheets: number; maxExpandedBytes: number; memoryMb: number },
): Promise<JsonIngestResult> {
  const inputBytes = Bun.file(inputPath).size;
  const instance = await openInstance(options.memoryMb, inputBytes);
  try {
    const conn = await instance.connect();
    try {
      const values = await loadSource(conn, inputPath, inputBytes);
      if (!values)
        throw new ToolError("INVALID_FILE", "The JSON file is empty.");
      // Several top-level values (JSON Lines) are one array of records.
      const rootExpression = values === 1 ? "json" : "to_json(list(json))";
      const structureReader = await conn.runAndReadAll(
        values === 1
          ? `SELECT json_type(json)::VARCHAR, json_structure(json)::VARCHAR FROM src`
          : `SELECT 'RECORDS', '[' || json_group_structure(json)::VARCHAR || ']' FROM src`,
      );
      const [rootType, structureText] = structureReader.getRowsJS()[0] as [
        string,
        string,
      ];
      const structure = parseStructure(structureText);
      const plans = findSheets(structure, options.maxSheets);
      await conn.run(
        `CREATE TEMPORARY TABLE doc AS SELECT ${rootExpression} AS json FROM src`,
      );
      const sheets: JsonSheetCsv[] = [];
      let total = 0;
      for (const [i, plan] of plans.entries()) {
        // A root record (no arrays) is one row; an array is one row per element.
        const rows =
          plan.kind === "record"
            ? `SELECT json->'${plan.json_path}' AS rec FROM doc`
            : `SELECT unnest(from_json(json->'${plan.json_path}', '["JSON"]')) AS rec FROM doc`;
        const outputPath = `${inputPath}.${i}.csv`;
        await conn.run(
          `COPY (${sheetSelect(recordColumns(plan.element), rows)}) TO ${quoteSqlString(outputPath)} (HEADER, DELIMITER ',')`,
        );
        const csv = Buffer.from(await Bun.file(outputPath).arrayBuffer());
        await Bun.file(outputPath).unlink();
        total += csv.length;
        if (total > options.maxExpandedBytes)
          throw new ToolError(
            "INGEST_LIMIT",
            "The JSON file expands beyond the table size limit.",
          );
        sheets.push({ name: plan.name, json_path: plan.json_path, csv });
      }
      const truncated = structureText.length > MAX_STRUCTURE_CHARS;
      return {
        sheets,
        summary: {
          root_type: rootType,
          values,
          structure: truncated
            ? structureText.slice(0, MAX_STRUCTURE_CHARS)
            : structureText,
          structure_truncated: truncated,
        },
      };
    } finally {
      conn.closeSync();
    }
  } finally {
    instance.closeSync();
  }
}

export type JsonExtractOutcome = {
  /** JSON text of the value at the path, or of the array of matches for a wildcard path. */
  value: string | null;
  /** JSON type of the value (OBJECT, ARRAY, VARCHAR, ...), or null when nothing is there. */
  type: string | null;
  /** Number of values a wildcard path matched; an exact path has 1 or 0. */
  matches: number;
  /** Length of the value when it is an array, so the model can page through it. */
  array_length?: number;
  truncated: boolean;
  total_chars: number;
};

/**
 * The value at a JSONPath in the file, as JSON text bounded by `maxChars`. The path is the
 * only untrusted input and is bound as a string literal; DuckDB resolves it. A wildcard
 * (`[*]`) returns every match as one array.
 */
export async function extractJsonPath(
  inputPath: string,
  path: string,
  options: { maxChars: number; memoryMb: number },
): Promise<JsonExtractOutcome> {
  const inputBytes = Bun.file(inputPath).size;
  const instance = await openInstance(options.memoryMb, inputBytes);
  try {
    const conn = await instance.connect();
    try {
      const values = await loadSource(conn, inputPath, inputBytes);
      if (!values)
        throw new ToolError("INVALID_FILE", "The JSON file is empty.");
      await conn.run(
        `CREATE TEMPORARY TABLE doc AS SELECT ${values === 1 ? "json" : "to_json(list(json))"} AS json FROM src`,
      );
      await conn.run(`SET enable_external_access = false`);
      const literal = quoteSqlString(path);
      const wildcard = path.includes("[*]");
      const reader = await conn.runAndReadAll(
        wildcard
          ? `SELECT to_json(json_extract(json, ${literal}))::VARCHAR, len(json_extract(json, ${literal})) FROM doc`
          : `SELECT json_extract(json, ${literal})::VARCHAR, json_type(json, ${literal})::VARCHAR, json_array_length(json, ${literal}) FROM doc`,
      );
      const row = reader.getRowsJS()[0] ?? [];
      const text = row[0] == null ? null : String(row[0]);
      if (wildcard) {
        const matches = Number(row[1] ?? 0);
        return bounded(
          matches ? text : null,
          matches ? "ARRAY" : null,
          matches,
          options.maxChars,
          matches,
        );
      }
      const type = row[1] == null ? null : String(row[1]);
      const arrayLength = type === "ARRAY" ? Number(row[2] ?? 0) : undefined;
      return bounded(
        text,
        type,
        text === null ? 0 : 1,
        options.maxChars,
        arrayLength,
      );
    } finally {
      conn.closeSync();
    }
  } finally {
    instance.closeSync();
  }
}

function bounded(
  text: string | null,
  type: string | null,
  matches: number,
  maxChars: number,
  arrayLength?: number,
): JsonExtractOutcome {
  const total = text?.length ?? 0;
  const truncated = total > maxChars;
  return {
    value: truncated ? text!.slice(0, maxChars) : text,
    type,
    matches,
    ...(arrayLength !== undefined ? { array_length: arrayLength } : {}),
    truncated,
    total_chars: total,
  };
}
