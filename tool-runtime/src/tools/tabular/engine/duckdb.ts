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

export type DescribeCsvResult = {
  columns: TabularColumn[];
  rowCount: number;
  /** CSV lines that failed to parse/cast and were skipped (coverage signal). */
  rejectedRows: number;
  sampleRows: Array<Record<string, unknown>>;
};

/**
 * Enumerate distinct values for a column up to this cardinality. Above it the
 * list is too long to hand the model usefully — we fall back to a numeric/date
 * range (`min`/`max`) or, for high-cardinality text, just the count. 50 keeps
 * the inspect payload small while covering the columns the model actually needs
 * to know the exact values of (municipalities, categories, years, codes).
 */
const MAX_ENUMERATED_DISTINCT = 50;

/**
 * Run `DESCRIBE` + `COUNT(*)` + a 5-row sample query against a local CSV path
 * via DuckDB's native `read_csv_auto`. Used by the ingest path to cache
 * schema/sample into `uploaded_file.tabular_metadata` so `inspect_table`
 * never has to re-parse the file.
 *
 * Malformed lines do not fail the ingest: the count scan runs with
 * `store_rejects = true` (which implies skipping faulty lines) and the number
 * of rejected lines is returned so the envelope can report partial coverage
 * instead of the file silently failing or silently passing.
 */
export async function describeCsv(
  csvPath: string,
  explicitHeader = false,
): Promise<DescribeCsvResult> {
  const conn = await openIngestConnection();
  try {
    const csvLit = quoteSqlString(csvPath) + (explicitHeader ? ", header = true" : "");

    const descReader = await conn.runAndReadAll(
      `DESCRIBE SELECT * FROM read_csv_auto(${csvLit}, ignore_errors = true)`,
    );
    const descRows = descReader.getRowObjectsJS();
    const columns = descRows.map((r) => ({
      name: String(r.column_name),
      type: String(r.column_type),
    }));

    const countReader = await conn.runAndReadAll(
      `SELECT COUNT(*) AS n FROM read_csv_auto(${csvLit}, store_rejects = true)`,
    );
    const countCell = countReader.getRowsJS()[0]?.[0];
    const rowCount = toFiniteNumber(countCell);

    // One row can carry several cast errors; DISTINCT line = skipped CSV lines.
    const rejectReader = await conn.runAndReadAll(
      `SELECT COUNT(DISTINCT line) AS n FROM reject_errors`,
    );
    const rejectedRows = toFiniteNumber(rejectReader.getRowsJS()[0]?.[0]);

    const sampleReader = await conn.runAndReadAll(
      `SELECT * FROM read_csv_auto(${csvLit}, ignore_errors = true) LIMIT 5`,
    );
    const sampleRows = sampleReader.getRowObjectsJson() as Array<Record<string, unknown>>;

    if (columns.length > 200) throw new Error("Too many columns (maximum 200)");
    const profiles = await profileColumns(conn, csvLit, columns);
    const columnsWithProfile: TabularColumn[] = columns.map((c, i) => ({
      ...c,
      profile: profiles[i],
    }));

    return { columns: columnsWithProfile, rowCount, rejectedRows, sampleRows };
  } finally {
    conn.closeSync();
  }
}

/**
 * Build the per-column value profile in two server-trusted scans:
 *   1. distinct-count for every column + min/max for the numeric/temporal ones.
 *   2. the enumerated distinct values for the columns whose distinct-count came
 *      in at or below `MAX_ENUMERATED_DISTINCT` (so the model gets the exact
 *      filter values, not a sample).
 * Each column resolves to one of three shapes: enumerated `values` (low-card),
 * `min`/`max` range (wide numeric/temporal), or just `distinctCount`
 * (high-card text — an id or free-text column not worth enumerating).
 */
async function profileColumns(
  conn: DuckDBConnection,
  csvLit: string,
  columns: Array<{ name: string; type: string }>,
): Promise<Array<NonNullable<TabularColumn["profile"]>>> {
  if (columns.length === 0) return [];

  // Scan 1: distinct counts (all columns) + min/max (range types only).
  const aggSelects: string[] = [];
  columns.forEach((c, i) => {
    const col = quoteIdent(c.name);
    aggSelects.push(`count(DISTINCT ${col}) AS d${i}`);
    if (isRangeType(c.type)) {
      aggSelects.push(`min(${col})::VARCHAR AS lo${i}`);
      aggSelects.push(`max(${col})::VARCHAR AS hi${i}`);
    }
  });
  const aggReader = await conn.runAndReadAll(
    `SELECT ${aggSelects.join(", ")} FROM read_csv_auto(${csvLit}, ignore_errors = true)`,
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
      `SELECT ${valSelects.join(", ")} FROM read_csv_auto(${csvLit}, ignore_errors = true)`,
    );
    const valRow = (valReader.getRowObjectsJson()[0] ?? {}) as Record<string, unknown>;
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
    if (values) return { distinctCount, values };
    if (isRangeType(c.type)) {
      const min = agg[`lo${i}`];
      const max = agg[`hi${i}`];
      return {
        distinctCount,
        ...(min !== null && min !== undefined ? { min: String(min) } : {}),
        ...(max !== null && max !== undefined ? { max: String(max) } : {}),
      };
    }
    return { distinctCount };
  });
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
export type RunQueryInput = {
  csvPath: string;
  explicitHeader?: boolean;
  sql: string;
  /** Further CSV files materialized as additional tables named by alias (never `t`). */
  tables?: { alias: string; csvPath: string; explicitHeader?: boolean }[];
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
        `CREATE TEMPORARY TABLE t AS SELECT * FROM read_csv_auto(${quoteSqlString(input.csvPath)}${input.explicitHeader ? ", header = true" : ""}, store_rejects = true)`,
      );
      for (const table of input.tables ?? []) {
        if (!TABLE_ALIAS.test(table.alias) || table.alias === "t")
          throw new QueryRejectedError(`Invalid table alias: ${table.alias}`);
        await conn.run(
          `CREATE TEMPORARY TABLE ${table.alias} AS SELECT * FROM read_csv_auto(${quoteSqlString(table.csvPath)}${table.explicitHeader ? ", header = true" : ""}, ignore_errors = true)`,
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
        const planReader = await runWithTimeout(conn, `EXPLAIN ${wrapped}`, timeoutMs);
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
      return { columns, rows, returnedRows: rows.length, truncated, parsedRows, rejectedRows };
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
        `query exceeded ${timeoutMs}ms timeout — refine with WHERE / LIMIT or simpler aggregates`,
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
 * exposes its `statementType`. Parse errors propagate as the raw DuckDB
 * message (caught upstream and surfaced as `{error, sql}` to the LLM).
 */
async function assertSingleReadOnlyStatement(conn: DuckDBConnection, sql: string): Promise<void> {
  let extracted: DuckDBExtractedStatements;
  try {
    extracted = await conn.extractStatements(sql);
  } catch (err) {
    // Re-throw with the same message so the tool's outer catch surfaces it
    // verbatim. Don't wrap in QueryRejectedError — parse errors are LLM
    // syntax errors, not authorization rejections.
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
