import type { TabularColumn } from "./engine/types";
import type { JsonExtractOutcome, JsonSummary } from "./engine/json-to-csv";
import type { TabularConfig } from "./config";

/** How the downloaded bytes are read: by their filename's extension. */
export type SourceFormat = "csv" | "xlsx" | "json";

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
  /** Lines above the header (a report title) that every read of this sheet skips. */
  skipRows?: number;
  /** For a sheet of a JSON file: the path of the array (or record) it holds. */
  jsonPath?: string;
};

/** What one ingest produced and the cache keeps: the sheets, and for JSON the tree summary. */
export type IngestResult = { sheets: SheetMetadata[]; json?: JsonSummary };

/** Child job: validate and convert one downloaded file, writing sheet CSVs to `outputDir`. */
export type IngestJob = {
  kind: "tabular_ingest";
  selection?: import("./selection").SourceSelection;
  inputPath: string;
  format: SourceFormat;
  contentType: string;
  outputDir: string;
  config: TabularConfig;
};

/** Child job: the value at a JSONPath in a downloaded JSON file. */
export type JsonExtractJob = {
  kind: "json_extract";
  inputPath: string;
  path: string;
  maxChars: number;
  config: TabularConfig;
};
export type { JsonExtractOutcome };

/** Child job: one read-only query (or a list of checks) over already-parsed sheet CSVs. */
export type QueryJob = {
  kind: "tabular_query";
  csvPath: string;
  explicitHeader?: boolean;
  skipRows?: number;
  tables: {
    alias: string;
    csvPath: string;
    explicitHeader?: boolean;
    skipRows?: number;
  }[];
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
  /** Cells cut to MAX_CELL_CHARS in the returned rows. */
  clippedCells?: number;
};

/** Per statement: a result, or the safe reason it was rejected. */
export type QueryJobResult = {
  results: Array<
    | { ok: true; outcome: QueryOutcome }
    | { ok: false; code: string; message: string }
  >;
};
