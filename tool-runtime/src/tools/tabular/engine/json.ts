/**
 * JSON in the file-analysis tools. Runs inside sandbox children only (trusted ingest lane).
 *
 * Two shapes, two readings. A JSON Lines file (.jsonl, .ndjson) is one record per line, a
 * table without a tree: its records are written as one sheet CSV, nested objects as dotted
 * columns ("addr.city"), arrays and deeper objects as JSON text that DuckDB's json functions
 * read in a query. A JSON document (.json) is a tree: query_json reads its structure (types
 * in place of values) and the value at a path. It is never turned into sheets; where its
 * tables are is a guess, and a document of settings has none.
 */
import { DuckDBInstance, type DuckDBConnection } from "@duckdb/node-api";
import { ToolError } from "../../../errors";
import { spillDirectory } from "./duckdb";

/** A JSON document described: what query_json returns without a path. */
export type JsonStructure = {
  /** OBJECT, ARRAY or a scalar type; "RECORDS" for several top-level values. */
  root_type: string;
  /** Top-level values in the file: 1 for an ordinary document. */
  values: number;
  /** DuckDB's inferred structure of the whole file (types in place of values), bounded. */
  structure: string;
  structure_truncated: boolean;
};

export type JsonValue = {
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

/** What one query_json call reads: the structure without a path, else the value at it. */
export type JsonReadOutcome = JsonStructure | JsonValue;

/** Deepest object nesting flattened to dotted columns; deeper values stay JSON text. */
const FLATTEN_DEPTH = 4;
/** Columns the sheet may hold; the rest of the record stays in a single JSON column. */
const MAX_COLUMNS = 200;
const MAX_STRUCTURE_CHARS = 6_000;
/** The column holding each line of a file whose lines are not objects. */
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

/** One instance and connection for one file, closed whatever happens. */
async function withFile<T>(
  inputPath: string,
  memoryMb: number,
  read: (conn: DuckDBConnection, values: number) => Promise<T>,
): Promise<T> {
  const inputBytes = Bun.file(inputPath).size;
  const instance = await openInstance(memoryMb, inputBytes);
  try {
    const conn = await instance.connect();
    try {
      const values = await loadSource(conn, inputPath, inputBytes);
      if (!values)
        throw new ToolError("INVALID_FILE", "The JSON file is empty.");
      return await read(conn, values);
    } finally {
      conn.closeSync();
    }
  } finally {
    instance.closeSync();
  }
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
 * The SELECT that writes the sheet, one line of the file per row. A JSON function parses its
 * whole input on every call, so the columns are extracted with one list-valued call for the
 * text columns and one for the JSON columns: two parses per record, not one per column.
 */
function sheetSelect(columns: Column[]): string {
  const paths =
    "[" + columns.map((c) => quoteSqlString(c.path)).join(", ") + "]";
  const select = columns
    .map((c, i) => `${c.text ? "t" : "j"}[${i + 1}] AS ${quoteIdent(c.name)}`)
    .join(", ");
  return `SELECT ${select} FROM (SELECT json->>${paths} AS t, json->${paths} AS j FROM src)`;
}

/**
 * Reads a JSON Lines file and returns its records as one sheet CSV, bounded by the caller.
 * The record type is the union of every line's keys, as DuckDB infers it.
 */
export async function convertJsonLinesToCsv(
  inputPath: string,
  options: { maxExpandedBytes: number; memoryMb: number },
): Promise<Buffer> {
  return withFile(inputPath, options.memoryMb, async (conn) => {
    const structureReader = await conn.runAndReadAll(
      `SELECT '[' || json_group_structure(json)::VARCHAR || ']' FROM src`,
    );
    const structure = parseStructure(
      String(structureReader.getRowsJS()[0]![0]),
    );
    const element = Array.isArray(structure)
      ? (structure[0] ?? "JSON")
      : "JSON";
    const outputPath = `${inputPath}.csv`;
    await conn.run(
      `COPY (${sheetSelect(recordColumns(element))}) TO ${quoteSqlString(outputPath)} (HEADER, DELIMITER ',')`,
    );
    const csv = Buffer.from(await Bun.file(outputPath).arrayBuffer());
    await Bun.file(outputPath).unlink();
    if (csv.length > options.maxExpandedBytes)
      throw new ToolError(
        "INGEST_LIMIT",
        "The JSON Lines file expands beyond the table size limit.",
      );
    return csv;
  });
}

/**
 * A JSON document read: its structure when `path` is undefined, else the value at the path
 * as JSON text bounded by `maxChars`. The path is the only untrusted input and is bound as
 * a string literal; DuckDB resolves it. A wildcard (`[*]`) returns every match as one array.
 * Several top-level values (concatenated JSON) are read as one array of them.
 */
export async function readJson(
  inputPath: string,
  path: string | undefined,
  options: { maxChars: number; memoryMb: number },
): Promise<JsonReadOutcome> {
  return withFile(inputPath, options.memoryMb, async (conn, values) => {
    if (path === undefined) {
      const reader = await conn.runAndReadAll(
        values === 1
          ? `SELECT json_type(json)::VARCHAR, json_structure(json)::VARCHAR FROM src`
          : `SELECT 'RECORDS', '[' || json_group_structure(json)::VARCHAR || ']' FROM src`,
      );
      const [rootType, text] = reader.getRowsJS()[0] as [string, string];
      const truncated = text.length > MAX_STRUCTURE_CHARS;
      return {
        root_type: rootType,
        values,
        structure: truncated ? text.slice(0, MAX_STRUCTURE_CHARS) : text,
        structure_truncated: truncated,
      };
    }
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
  });
}

function bounded(
  text: string | null,
  type: string | null,
  matches: number,
  maxChars: number,
  arrayLength?: number,
): JsonValue {
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
