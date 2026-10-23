/**
 * Extracted tabular engine. Trusted ingestion and untrusted queries use separate
 * instances. Materialize the authorized CSV first, then disable external access
 * and extensions and lock configuration BEFORE preparing any user statement.
 * Only a single SELECT is accepted; row caps and interruption bound execution.
 * The worker adds process isolation and a deadline covering the complete job.
 */
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  DuckDBInstance,
  StatementType,
  type DuckDBConnection,
  type DuckDBExtractedStatements,
} from "@duckdb/node-api";
import { defaultQueryLimits as tabularQueryLimits } from "../config";
import type { TabularColumn } from "./types";

/**
 * Process-global instance for the ingest lane. Never executes LLM-supplied
 * SQL, so it doesn't need the per-call lockdown that `runQuery` uses.
 */
/**
 * Where DuckDB spills when a query outgrows its memory limit. Set explicitly because the
 * default is relative to the working directory, which a confined child cannot write to.
 */
export function spillDirectory(): string {
  return join(tmpdir(), "duckdb-spill");
}

let _ingestInstance: Promise<DuckDBInstance> | null = null;
function getIngestInstance(): Promise<DuckDBInstance> {
  if (!_ingestInstance)
    _ingestInstance = DuckDBInstance.create(":memory:", {
      memory_limit: "256MB",
      temp_directory: spillDirectory(),
      max_temp_directory_size: "256MB",
      threads: "1",
      allow_community_extensions: "false",
      autoinstall_known_extensions: "false",
      autoload_known_extensions: "false",
    });
  return _ingestInstance;
}

async function openIngestConnection(): Promise<DuckDBConnection> {
  const instance = await getIngestInstance();
  return instance.connect();
}

function quoteSqlString(value: string): string {
  return "'" + value.replaceAll("'", "''") + "'";
}

/** How a sheet CSV is read: the same options at ingest and at query time, so types agree. */
export type CsvReadOptions = {
  /** The first line is the header, whatever the sniffer thinks (exact selections). */
  explicitHeader?: boolean;
  /** Lines above the header (a report title, a blank line) found at ingest. */
  skipRows?: number;
};

/**
 * The `read_csv_auto` call for a sheet CSV. `sample_size = -1` types every column from the
 * whole file: a column that is numeric for 20,000 rows and then holds "N/A" becomes text
 * instead of silently losing that row, and inspect and query see the same types.
 */
function readCsv(
  csvPath: string,
  options: CsvReadOptions,
  errors: "store_rejects" | "ignore_errors",
): string {
  const parts = [
    quoteSqlString(csvPath),
    "sample_size = -1",
    `${errors} = true`,
  ];
  if (options.explicitHeader) parts.push("header = true");
  if (options.skipRows) parts.push(`skip = ${options.skipRows}`);
  return `read_csv_auto(${parts.join(", ")})`;
}

export type DescribeCsvResult = {
  columns: TabularColumn[];
  rowCount: number;
  /** CSV lines that failed to parse/cast and were skipped (coverage signal). */
  rejectedRows: number;
  sampleRows: Array<Record<string, unknown>>;
  /** Lines above the header that queries must skip too; absent when the header is line 1. */
  skipRows?: number;
};

/**
 * Enumerate distinct values for a column up to this cardinality. Above it the
 * list is too long to hand the model usefully — we fall back to a numeric/date
 * range (`min`/`max`) or, for high-cardinality text, just the count. 50 keeps
 * the inspect payload small while covering the columns the model actually needs
 * to know the exact values of (municipalities, categories, years, codes).
 */
const MAX_ENUMERATED_DISTINCT = 50;

/** Most title lines a report puts above its header; probing stops here. */
const MAX_SKIPPED_LINES = 10;
/** The name DuckDB gives a column whose header cell is missing or blank. */
const GENERIC_COLUMN = /^column\d+$/;

/**
 * Materialize the CSV once in a per-connection temp table, then describe, count, sample and
 * profile it. Used by the ingest path to cache schema and samples so `inspect_table` never
 * has to re-parse the file.
 *
 * Malformed lines do not fail the ingest: the scan runs with `store_rejects = true` (which
 * skips faulty lines) and the number of rejected lines is returned so the envelope reports
 * partial coverage. Counting after materialization matters: a bare `COUNT(*)` over
 * `read_csv_auto` never casts the columns, so it saw none of the cast rejections a query
 * later hits.
 *
 * Unless the caller fixed the header (exact selections), lines above the header are
 * detected and skipped; see `detectSkippedLines`.
 */
export async function describeCsv(
  csvPath: string,
  options: CsvReadOptions = {},
): Promise<DescribeCsvResult> {
  const conn = await openIngestConnection();
  try {
    const skipRows = options.explicitHeader
      ? 0
      : (options.skipRows ?? (await detectSkippedLines(conn, csvPath)));
    const read = { explicitHeader: options.explicitHeader, skipRows };
    await conn.run(
      `CREATE TEMPORARY TABLE src AS SELECT * FROM ${readCsv(csvPath, read, "store_rejects")}`,
    );

    const descReader = await conn.runAndReadAll(`DESCRIBE src`);
    const columns = descReader.getRowObjectsJS().map((r) => ({
      name: String(r.column_name),
      type: String(r.column_type),
    }));
    if (columns.length > 200) throw new Error("Too many columns (maximum 200)");

    const countReader = await conn.runAndReadAll(
      `SELECT COUNT(*) AS n FROM src`,
    );
    const rowCount = toFiniteNumber(countReader.getRowsJS()[0]?.[0]);

    // One row can carry several cast errors; DISTINCT line = skipped CSV lines. The reject
    // tables are per connection, and this connection scanned the file exactly once.
    const rejectReader = await conn.runAndReadAll(
      `SELECT COUNT(DISTINCT line) AS n FROM reject_errors`,
    );
    const rejectedRows = toFiniteNumber(rejectReader.getRowsJS()[0]?.[0]);

    const sampleReader = await conn.runAndReadAll(`SELECT * FROM src LIMIT 5`);
    const sampleRows = sampleReader.getRowObjectsJson() as Array<
      Record<string, unknown>
    >;

    const profiles = await profileColumns(conn, columns);
    const columnsWithProfile: TabularColumn[] = columns.map((c, i) => ({
      ...c,
      profile: profiles[i],
    }));

    return {
      columns: columnsWithProfile,
      rowCount,
      rejectedRows,
      sampleRows,
      ...(skipRows ? { skipRows } : {}),
    };
  } finally {
    conn.closeSync();
  }
}

/**
 * Lines above the header, as reports export them: a title in A1, a blank line, then the
 * table. Read as is, the title becomes one column name and the rest `column1`, `column2`,
 * … while the real header turns into a data row that makes every column text.
 *
 * The sniffer's own schema tells when that happened (generic names, or all text with a
 * generic name). Only then are `skip = 1 … MAX_SKIPPED_LINES` tried, on the default sample,
 * and the first that yields a header with distinct, non-generic names for at least two
 * columns wins. A header-less file never qualifies, so none of its rows is skipped.
 */
async function detectSkippedLines(
  conn: DuckDBConnection,
  csvPath: string,
): Promise<number> {
  const schema = async (skip: number) => {
    const parts = [quoteSqlString(csvPath), "ignore_errors = true"];
    if (skip) parts.push(`skip = ${skip}`);
    const reader = await conn.runAndReadAll(
      `DESCRIBE SELECT * FROM read_csv_auto(${parts.join(", ")})`,
    );
    return reader
      .getRowObjectsJS()
      .map((r) => ({
        name: String(r.column_name),
        type: String(r.column_type),
      }));
  };
  const first = await schema(0);
  const generic = first.filter((c) => GENERIC_COLUMN.test(c.name)).length;
  const allText = first.every((c) => c.type === "VARCHAR");
  if (generic === 0 || (generic * 2 < first.length && !allText)) return 0;
  for (let skip = 1; skip <= MAX_SKIPPED_LINES; skip++) {
    let candidate;
    try {
      candidate = await schema(skip);
    } catch {
      return 0;
    }
    const names = new Set(candidate.map((c) => c.name));
    if (
      candidate.length >= 2 &&
      names.size === candidate.length &&
      candidate.every((c) => !GENERIC_COLUMN.test(c.name))
    )
      return skip;
  }
  return 0;
}

/**
 * Text that DuckDB could not type but a model can, once told how. Each pattern pairs with
 * the SQL that converts the column; the share of non-null values matching decides whether
 * the hint is given. Dates need no entry: the sniffer already reads the common day-first
 * and ISO forms, dotted ones included.
 */
const TEXT_SHAPES: Array<{
  key: string;
  pattern: string;
  hint: (column: string) => string;
}> = [
  {
    // 1 234,50   15 000,00   987,25   12,5%   1.234,50 (space, no-break space or dot
    // thousands, comma decimals, optional percent). Plain digits match too, which is
    // what a numeric column with a few "N/A" cells looks like after full-file typing.
    key: "decimal_comma",
    pattern: "^\\s*[-+]?(\\d{1,3}([  .]\\d{3})+|\\d+)(,\\d+)?\\s*%?\\s*$",
    hint: (column) =>
      `Numeric text with a comma decimal separator and space or dot thousands separators; a percent sign may follow. Cast with TRY_CAST(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(${column}, ' ', ''), chr(160), ''), '.', ''), '%', ''), ',', '.') AS DOUBLE); other text becomes NULL.`,
  },
  {
    // 1,234.56   12.5%   1,000 (comma thousands, dot decimals, optional percent).
    key: "decimal_point",
    pattern: "^\\s*[-+]?(\\d{1,3}(,\\d{3})+|\\d+)(\\.\\d+)?\\s*%?\\s*$",
    hint: (column) =>
      `Numeric text with comma thousands separators or a percent sign. Cast with TRY_CAST(REPLACE(REPLACE(${column}, ',', ''), '%', '') AS DOUBLE); other text becomes NULL.`,
  },
];
/** Share of a text column's values a shape must match before its hint is given. */
const TEXT_SHAPE_SHARE = 0.9;

/**
 * Build the per-column value profile in two server-trusted scans over the materialized
 * table:
 *   1. distinct-count for every column, min/max for the numeric/temporal ones, and for
 *      text columns three example values plus the share matching each `TEXT_SHAPES` entry.
 *   2. the enumerated distinct values for the columns whose distinct-count came
 *      in at or below `MAX_ENUMERATED_DISTINCT` (so the model gets the exact
 *      filter values, not a sample).
 * Each column resolves to one of three shapes: enumerated `values` (low-card),
 * `min`/`max` range (wide numeric/temporal), or `distinctCount` with `examples`
 * (high-card text — an id or free-text column not worth enumerating). A text column that
 * is really numbers or dates in a local format also carries a `hint` with the cast to use.
 */
async function profileColumns(
  conn: DuckDBConnection,
  columns: Array<{ name: string; type: string }>,
): Promise<Array<NonNullable<TabularColumn["profile"]>>> {
  if (columns.length === 0) return [];

  // Scan 1: distinct counts (all columns), min/max (range types), examples and shape
  // shares (text).
  const aggSelects: string[] = [];
  columns.forEach((c, i) => {
    const col = quoteIdent(c.name);
    aggSelects.push(`count(DISTINCT ${col}) AS d${i}`);
    if (isRangeType(c.type)) {
      aggSelects.push(`min(${col})::VARCHAR AS lo${i}`);
      aggSelects.push(`max(${col})::VARCHAR AS hi${i}`);
    }
    if (c.type === "VARCHAR") {
      aggSelects.push(
        `min(${col}) AS e${i}_0`,
        `quantile_disc(${col}, 0.5) AS e${i}_1`,
        `max(${col}) AS e${i}_2`,
      );
      for (const shape of TEXT_SHAPES)
        aggSelects.push(
          `avg(CASE WHEN ${col} IS NULL THEN NULL WHEN regexp_matches(${col}, ${quoteSqlString(shape.pattern)}) THEN 1 ELSE 0 END) AS ${shape.key}${i}`,
        );
    }
  });
  const aggReader = await conn.runAndReadAll(
    `SELECT ${aggSelects.join(", ")} FROM src`,
  );
  const agg = (aggReader.getRowObjectsJS()[0] ?? {}) as Record<string, unknown>;

  // The columns we'll enumerate exact values for.
  const lowCard = columns
    .map((c, i) => ({ i, d: toFiniteNumber(agg[`d${i}`]) }))
    .filter(({ d }) => d > 0 && d <= MAX_ENUMERATED_DISTINCT);

  // Scan 2 (only if there's anything to enumerate): the distinct value lists.
  const valuesByIndex = new Map<number, string[]>();
  if (lowCard.length > 0) {
    const valSelects = lowCard.map(
      ({ i }) => `list(DISTINCT ${quoteIdent(columns[i]!.name)}) AS v${i}`,
    );
    const valReader = await conn.runAndReadAll(
      `SELECT ${valSelects.join(", ")} FROM src`,
    );
    const valRow = (valReader.getRowObjectsJson()[0] ?? {}) as Record<
      string,
      unknown
    >;
    for (const { i } of lowCard) {
      const raw = valRow[`v${i}`];
      if (!Array.isArray(raw)) continue;
      const values = raw
        .filter((v) => v !== null && v !== undefined)
        .map((v) => String(v))
        .sort(compareValues);
      valuesByIndex.set(i, values);
    }
  }

  return columns.map((c, i) => {
    const distinctCount = toFiniteNumber(agg[`d${i}`]);
    const values = valuesByIndex.get(i);
    const hint =
      c.type === "VARCHAR" ? textHint(agg, i, quoteIdent(c.name)) : undefined;
    if (values) return { distinctCount, values, ...(hint ? { hint } : {}) };
    if (isRangeType(c.type)) {
      const min = agg[`lo${i}`];
      const max = agg[`hi${i}`];
      return {
        distinctCount,
        ...(min !== null && min !== undefined ? { min: String(min) } : {}),
        ...(max !== null && max !== undefined ? { max: String(max) } : {}),
      };
    }
    if (c.type !== "VARCHAR") return { distinctCount };
    const examples = [
      ...new Set(
        [agg[`e${i}_0`], agg[`e${i}_1`], agg[`e${i}_2`]]
          .filter((v) => v !== null && v !== undefined)
          .map((v) => String(v)),
      ),
    ];
    return {
      distinctCount,
      ...(examples.length ? { examples } : {}),
      ...(hint ? { hint } : {}),
    };
  });
}

/** The cast hint for text column `i`, when one shape covers enough of its values. */
function textHint(
  agg: Record<string, unknown>,
  i: number,
  column: string,
): string | undefined {
  for (const shape of TEXT_SHAPES) {
    const share = agg[`${shape.key}${i}`];
    if (typeof share === "number" && share >= TEXT_SHAPE_SHARE)
      return shape.hint(column);
  }
  return undefined;
}

/** Quote an identifier for safe inclusion in DuckDB SQL (server-trusted lane). */
function quoteIdent(name: string): string {
  return `"${name.replace(/"/g, '""')}"`;
}

/**
 * True for the DuckDB types where a `min`/`max` range is the useful summary
 * when a column has too many distinct values to enumerate. Text/boolean fall
 * through to count-only.
 */
function isRangeType(type: string): boolean {
  const t = type.toUpperCase();
  if (t.startsWith("DECIMAL") || t.startsWith("NUMERIC")) return true;
  return RANGE_TYPES.has(t);
}

const RANGE_TYPES = new Set<string>([
  "TINYINT",
  "SMALLINT",
  "INTEGER",
  "BIGINT",
  "HUGEINT",
  "UTINYINT",
  "USMALLINT",
  "UINTEGER",
  "UBIGINT",
  "UHUGEINT",
  "FLOAT",
  "REAL",
  "DOUBLE",
  "DATE",
  "TIME",
  "TIMETZ",
  "TIMESTAMP",
  "TIMESTAMPTZ",
  "TIMESTAMP_S",
  "TIMESTAMP_MS",
  "TIMESTAMP_NS",
  "TIMESTAMP WITH TIME ZONE",
]);

/** Sort enumerated values numerically when both parse as numbers, else by locale. */
function compareValues(a: string, b: string): number {
  const na = Number(a);
  const nb = Number(b);
  if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
  return a.localeCompare(b);
}

export const TABLE_ALIAS = /^[a-z][a-z0-9_]{0,30}$/;
export type RunQueryInput = CsvReadOptions & {
  csvPath: string;
  sql: string;
  /** Further CSV files materialized as additional tables named by alias (never `t`). */
  tables?: ({ alias: string; csvPath: string } & CsvReadOptions)[];
  /** Maximum rows returned to the caller. The wrapper requests `rowLimit + 1`
   *  so we can detect truncation. Defaults to `tabularQueryLimits().rowLimit`. */
  rowLimit?: number;
  /** Hard timeout on the user query in milliseconds. On expiry we call
   *  `conn.interrupt()` and throw `QueryRejectedError`. Defaults to
   *  `tabularQueryLimits().timeoutMs`. */
  timeoutMs?: number;
  /** Per-query DuckDB `memory_limit` (MB). Defaults to the configured value. */
  memoryMb?: number;
  /** Per-query `max_temp_directory_size` (MB) — spill-to-disk cap. Defaults to
   *  the configured value. */
  tempMb?: number;
  /** Per-query DuckDB `threads`. Defaults to the configured value. */
  threads?: number;
  /**
   * Dry-run: validate the SQL, then return DuckDB's `EXPLAIN` plan (with its
   * estimated cardinalities) instead of executing the query. The user SQL is
   * still SELECT-gated; the EXPLAIN wrapper is server-constructed — user-
   * written EXPLAIN remains rejected (it would break the row-limit wrapper).
   */
  explainOnly?: boolean;
};

export type RunQueryResult = {
  columns: string[];
  rows: unknown[][];
  /** Rows actually included in `rows`. Capped at `rowLimit`. */
  returnedRows: number;
  /** True when the query produced more than `rowLimit` rows. */
  truncated: boolean;
  /** CSV rows that parsed into the table the query ran over. */
  parsedRows: number;
  /**
   * CSV lines that failed to parse/cast and were skipped before the query ran.
   * Non-zero means the query saw a partial view of the file — the coverage
   * signal that lets a caller distinguish "the answer" from "the answer over
   * the 87% that parsed".
   */
  rejectedRows: number;
};

/**
 * Thrown when the supplied SQL fails a structural gate (multi-statement,
 * not a SELECT, etc.). Carries an LLM-facing message — the tool builder
 * surfaces these directly without prepending "DuckDB error".
 */
export class QueryRejectedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "QueryRejectedError";
  }
}

/**
 * StatementType ids the sandbox allows. SELECT only — anything else is
 * either a mutation (INSERT/UPDATE/DELETE/COPY/DROP/ALTER), a privileged
 * operation (ATTACH/DETACH/SET/LOAD/EXTENSION), or a meta-statement we
 * can't safely subquery into our `SELECT * FROM (…)` row-limiter wrapper
 * (EXPLAIN/PRAGMA). If real demand surfaces for EXPLAIN we'd special-case
 * it to skip the wrap; for now keep the surface tight.
 */
const ALLOWED_USER_STATEMENT_TYPES = new Set<number>([StatementType.SELECT]);

/**
 * Execute a SQL string against the CSV at `csvPath` inside a per-query
 * sandbox. See the module header for the full hardening sequence; in short:
 * materialize CSV → lock configuration → validate statement type → execute
 * the wrapped query with interruption.
 *
 * The instance is closed in `finally`, so the per-call lockdown is
 * contained — the next call gets a fresh instance.
 */
export async function runQuery(input: RunQueryInput): Promise<RunQueryResult> {
  const limits = tabularQueryLimits();
  const rowLimit = input.rowLimit ?? limits.rowLimit;
  const timeoutMs = input.timeoutMs ?? limits.timeoutMs;
  const memoryMb = input.memoryMb ?? limits.memoryMb;
  const tempMb = input.tempMb ?? limits.tempMb;
  const threads = input.threads ?? limits.threads;
  // LLMs habitually terminate SQL with `;`. The single-trailing form is
  // syntactically equivalent to the bare statement, but our row-limiter
  // wrapper (`SELECT * FROM (<user>) AS _user_q LIMIT N`) makes the `;`
  // a parse error inside parens, so the call would fail and the model
  // would retry without it — producing a duplicate tool-call card in the
  // UI trace. Strip a single trailing `;`; interior `;` still trips the
  // multi-statement gate below.
  const sql = input.sql.replace(/\s*;\s*$/, "");
  const instance = await DuckDBInstance.create(":memory:", {
    memory_limit: `${memoryMb}MB`,
    temp_directory: spillDirectory(),
    max_temp_directory_size: `${tempMb}MB`,
    threads: String(threads),
    allow_community_extensions: "false",
    autoinstall_known_extensions: "false",
    autoload_known_extensions: "false",
  });
  try {
    const conn = await instance.connect();
    try {
      // 1. Materialize into memory. Must happen before lockdown (the CSV
      //    read needs the local filesystem) and before validation (so
      //    `prepare()` can resolve `t`). `store_rejects = true` skips
      //    malformed lines instead of failing the whole scan and records
      //    them in `reject_errors` — counted below for the coverage envelope.
      await conn.run(
        `CREATE TEMPORARY TABLE t AS SELECT * FROM ${readCsv(input.csvPath, input, "store_rejects")}`,
      );
      for (const table of input.tables ?? []) {
        if (!TABLE_ALIAS.test(table.alias) || table.alias === "t")
          throw new QueryRejectedError(`Invalid table alias: ${table.alias}`);
        await conn.run(
          `CREATE TEMPORARY TABLE ${table.alias} AS SELECT * FROM ${readCsv(table.csvPath, table, "ignore_errors")}`,
        );
      }

      // Coverage counts (server-trusted SQL, before lockdown). One CSV line
      // can carry several cast errors; DISTINCT line = skipped lines.
      const parsedReader = await conn.runAndReadAll(`SELECT COUNT(*) FROM t`);
      const parsedRows = toFiniteNumber(parsedReader.getRowsJS()[0]?.[0]);
      const rejectReader = await conn.runAndReadAll(
        `SELECT COUNT(DISTINCT line) FROM reject_errors`,
      );
      const rejectedRows = toFiniteNumber(rejectReader.getRowsJS()[0]?.[0]);

      // Lock down BEFORE preparation: binding can access external resources.
      await conn.run(`SET enable_external_access = false`);
      await conn.run(`SET allow_community_extensions = false`);
      await conn.run(`SET autoinstall_known_extensions = false`);
      await conn.run(`SET autoload_known_extensions = false`);
      await conn.run(`SET memory_limit = '${memoryMb}MB'`);
      await conn.run(`SET max_temp_directory_size = '${tempMb}MB'`);
      await conn.run(`SET threads = ${threads}`);
      await conn.run(`SET lock_configuration = true`);
      await assertSingleReadOnlyStatement(conn, sql);

      // 4. Run the wrapped user query under a timeout race. In explain-only
      //    mode, plan the same wrapped statement instead of executing it —
      //    the plan text carries DuckDB's estimated cardinality per operator,
      //    a price tag the caller can read before paying for the real run.
      const wrapped = `SELECT * FROM (${sql}) AS _user_q LIMIT ${rowLimit + 1}`;
      if (input.explainOnly) {
        const planReader = await runWithTimeout(
          conn,
          `EXPLAIN ${wrapped}`,
          timeoutMs,
        );
        const planRows = planReader.getRowsJson() as unknown[][];
        return {
          columns: planReader.columnNames(),
          rows: planRows,
          returnedRows: planRows.length,
          truncated: false,
          parsedRows,
          rejectedRows,
        };
      }
      const reader = await runWithTimeout(conn, wrapped, timeoutMs);
      const columns = reader.columnNames();
      const allRows = reader.getRowsJson() as unknown[][];
      const truncated = allRows.length > rowLimit;
      const rows = truncated ? allRows.slice(0, rowLimit) : allRows;
      return {
        columns,
        rows,
        returnedRows: rows.length,
        truncated,
        parsedRows,
        rejectedRows,
      };
    } finally {
      conn.closeSync();
    }
  } finally {
    instance.closeSync();
  }
}

/**
 * Run a DuckDB query under a hard wall-clock timeout. On expiry we call
 * `conn.interrupt()` — this causes the in-flight `runAndReadAll` to throw —
 * and re-throw as `QueryRejectedError` with an LLM-facing message. If the
 * query finishes first, the timer is cleared and the result returns as-is.
 *
 * No Promise.race needed: the interrupt forces the awaited call to throw,
 * and we check the `timedOut` flag in the catch to decide which error to
 * surface.
 */
async function runWithTimeout(
  conn: DuckDBConnection,
  sql: string,
  timeoutMs: number,
): Promise<Awaited<ReturnType<DuckDBConnection["runAndReadAll"]>>> {
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    try {
      conn.interrupt();
    } catch {
      // Best-effort: interrupt may no-op if the query already returned.
    }
  }, timeoutMs);
  try {
    return await conn.runAndReadAll(sql);
  } catch (err) {
    if (timedOut) {
      throw new QueryRejectedError(
        `The query exceeded the ${timeoutMs} ms limit. Narrow it with WHERE or aggregate instead of returning every row.`,
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Validate that the LLM-supplied SQL is structurally something we'll
 * execute: exactly one statement, type SELECT. Anything else is
 * rejected with a clear message the LLM can act on.
 *
 * Implementation: ask DuckDB to parse-and-prepare. The prepared statement
 * exposes its `statementType`. Parse and binding errors propagate as the raw
 * DuckDB message; `executeQuery` passes those classes on to the model, since
 * they describe its own SQL (see `modelFacingDiagnostic`).
 */
async function assertSingleReadOnlyStatement(
  conn: DuckDBConnection,
  sql: string,
): Promise<void> {
  let extracted: DuckDBExtractedStatements;
  try {
    extracted = await conn.extractStatements(sql);
  } catch (err) {
    // Re-throw with the same message so the outer catch can classify it. Not a
    // QueryRejectedError: parse errors are LLM syntax errors, not authorization
    // rejections.
    throw err instanceof Error ? err : new Error(String(err));
  }
  if (extracted.count !== 1) {
    throw new QueryRejectedError(
      `query_table accepts exactly one statement; got ${extracted.count}. Combine into a single SELECT (CTEs are fine) or split into separate tool calls.`,
    );
  }
  const prepared = await extracted.prepare(0);
  try {
    if (!ALLOWED_USER_STATEMENT_TYPES.has(prepared.statementType)) {
      throw new QueryRejectedError(
        `query_table is read-only — only SELECT statements are allowed. The supplied statement type is not permitted.`,
      );
    }
  } finally {
    prepared.destroySync();
  }
}

/**
 * Coerce DuckDB's `getRowsJS()` cell value into a finite JS number. BIGINT
 * comes back as a JS bigint; we narrow to number for row counts (always well
 * below 2^53 — a CSV with that many rows wouldn't make it through ingest).
 */
function toFiniteNumber(value: unknown): number {
  if (typeof value === "bigint") return Number(value);
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return 0;
}
