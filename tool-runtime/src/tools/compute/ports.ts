export type ComputeJob = {
  kind: "compute";
  code: string;
  // JSON value exposed to the script as the global `input`.
  input: unknown;
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
  | "RESULT_TOO_LARGE";
export type ComputeOutcome = {
  ok: boolean;
  result?: unknown;
  error?: { code: ScriptErrorCode; name: string; message: string; line?: number };
  logs: string[];
  dropped_log_lines: number;
  duration_ms: number;
};
