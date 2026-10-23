import { z } from "zod";
// Results and logs travel through the sandbox child's bounded stdout (600 KiB) and the server's
// 512 KiB structured-result cap, so the sum of the result and log limits stays well below both.
export const computeConfigSchema = z
  .object({
    timeout_ms: z.number().int().min(100).max(30_000).default(5_000),
    memory_mb: z.number().int().min(8).max(256).default(64),
    max_code_chars: z.number().int().min(200).max(200_000).default(20_000),
    max_input_bytes: z
      .number()
      .int()
      .min(1024)
      .max(128 * 1024)
      .default(64 * 1024),
    max_result_bytes: z
      .number()
      .int()
      .min(1024)
      .max(384 * 1024)
      .default(256 * 1024),
    max_log_lines: z.number().int().min(0).max(500).default(100),
    // An exported value leaves the child as a CSV file, never on stdout, so it may be far
    // larger than a result; it still has to fit Eneo's generated-file limit of 20 MiB.
    export_row_limit: z.number().int().min(1).max(1_000_000).default(200_000),
    max_export_bytes: z
      .number()
      .int()
      .min(64 * 1024)
      .max(20 * 1024 * 1024)
      .default(20 * 1024 * 1024),
  })
  .strict();
export type ComputeConfig = z.infer<typeof computeConfigSchema>;
// Each captured console line is cut at this length; the line count is operator-set.
export const MAX_LOG_LINE_CHARS = 1000;
// Rows of an exported table kept in the result as a preview; the file holds them all.
export const PREVIEW_ROWS = 20;
