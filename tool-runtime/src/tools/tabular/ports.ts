import type { TabularColumn } from "./engine/types";
import type { TabularConfig } from "./config";

/** Formula values come from Excel's saved results; this runtime never recalculates. */
export type CalculationDiagnostics = {
  formula_cells: number;
  missing_cached_results: number;
  recalculated: false;
};

/** One parsed sheet as cached on disk: `csv` is the file name inside the cache entry. */
export type SheetMetadata = {
  name: string;
  columns: TabularColumn[];
  rowCount: number;
  rejectedRows: number;
  sampleRows: Array<Record<string, unknown>>;
  csv: string;
  calculation?: CalculationDiagnostics;
  queryable?: boolean;
  sourceRows?: number[];
  explicitHeader?: boolean;
};

/** Child job: validate and convert one downloaded file, writing sheet CSVs to `outputDir`. */
export type IngestJob = {
  kind: "tabular_ingest";
  selection?: import("./selection").SourceSelection;
  inputPath: string;
  isXlsx: boolean;
  contentType: string;
  outputDir: string;
  config: TabularConfig;
};

/** Child job: one read-only query (or a list of checks) over already-parsed sheet CSVs. */
export type QueryJob = {
  kind: "tabular_query";
  csvPath: string;
  explicitHeader?: boolean;
  tables: { alias: string; csvPath: string; explicitHeader?: boolean }[];
  statements: string[];
  explain: boolean;
  config: TabularConfig;
  /** Write the single statement's full result (up to `rowLimit` rows) as CSV here. */
  export?: { outputPath: string; rowLimit: number };
};

export type QueryOutcome = {
  columns: string[];
  rows: unknown[][];
  returnedRows: number;
  truncated: boolean;
  parsedRows: number;
  rejectedRows: number;
  /** Rows written to the export file, and whether the export hit its row limit. */
  exportedRows?: number;
  exportTruncated?: boolean;
};

/** Per statement: a result, or the safe reason it was rejected. */
export type QueryJobResult = {
  results: Array<
    { ok: true; outcome: QueryOutcome } | { ok: false; code: string; message: string }
  >;
};
