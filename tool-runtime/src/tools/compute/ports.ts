/** Where the child writes an exported table, and how much of it. */
export type ComputeExport = { outputPath: string; rowLimit: number; maxBytes: number };
export type ComputeJob = {
  kind: "compute";
  code: string;
  // JSON value exposed to the script as the global `input`.
  input: unknown;
  // Set when the returned table is to be delivered as a CSV file instead of inline.
  export?: ComputeExport;
};
// Failures that happen inside the script are part of the outcome, not tool errors: the model
// reads them next to the console output and fixes its code.
export type ScriptErrorCode =
  | "SYNTAX_ERROR"
  | "RUNTIME_ERROR"
  | "TIMEOUT"
  | "OUT_OF_MEMORY"
  | "UNSETTLED_PROMISE"
  | "RESULT_NOT_SERIALIZABLE"
  | "RESULT_NOT_TABULAR"
  | "RESULT_TOO_LARGE";
export type ComputeOutcome = {
  ok: boolean;
  // With an export, the first rows of the table in the shape the script returned them.
  result?: unknown;
  error?: { code: ScriptErrorCode; name: string; message: string; line?: number };
  logs: string[];
  dropped_log_lines: number;
  duration_ms: number;
  export?: { columns: string[]; rows: number; truncated: boolean; preview_rows: number };
};
