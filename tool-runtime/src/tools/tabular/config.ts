import { z } from "zod";

// Limits for one tabular call. Query limits bound the DuckDB child; intake limits bound the
// trusted download and the XLSX conversion.
export const tabularConfigSchema = z
  .object({
    row_limit: z.number().int().min(1).max(5000).default(500),
    query_timeout_ms: z.number().int().min(100).max(30_000).default(10_000),
    memory_mb: z.number().int().min(16).max(512).default(256),
    temp_mb: z.number().int().min(16).max(512).default(256),
    threads: z.number().int().min(1).max(2).default(1),
    max_expanded_bytes: z
      .number()
      .int()
      .min(1024)
      .max(128 * 1024 * 1024)
      .default(64 * 1024 * 1024),
    max_sheets: z.number().int().min(1).max(50).default(20),
    // Rows query_table writes to a CSV file when asked to export its result.
    export_row_limit: z.number().int().min(1).max(1_000_000).default(200_000),
    max_upload_bytes: z
      .number()
      .int()
      .min(1)
      .max(100 * 1024 * 1024)
      .default(20 * 1024 * 1024),
    download_timeout_ms: z.number().int().min(100).max(60_000).default(15_000),
    // Parsed sheets are kept this long on local disk; a miss re-downloads and re-parses.
    cache_ttl_ms: z
      .number()
      .int()
      .min(0)
      .max(24 * 60 * 60 * 1000)
      .default(30 * 60 * 1000),
    cache_max_bytes: z
      .number()
      .int()
      .min(0)
      .max(4 * 1024 * 1024 * 1024)
      .default(256 * 1024 * 1024),
  })
  .strict();
export type TabularConfig = z.infer<typeof tabularConfigSchema>;
export function defaultQueryLimits() {
  return { rowLimit: 500, timeoutMs: 10_000, memoryMb: 256, tempMb: 256, threads: 1 };
}
export function queryLimits(config: TabularConfig) {
  return {
    rowLimit: config.row_limit,
    timeoutMs: config.query_timeout_ms,
    memoryMb: config.memory_mb,
    tempMb: config.temp_mb,
    threads: config.threads,
  };
}

/** One origin that signed file URLs may point at; private addresses need an explicit opt-in. */
export type DownloadOrigin = { origin: string; allow_private: boolean };
/** What one download may do: the origins it may target and its byte and time limits. */
export type DownloadPolicy = Pick<TabularConfig, "max_upload_bytes" | "download_timeout_ms"> & {
  allowed_origins: DownloadOrigin[];
};

// Some container environments resolve Docker's host alias to this synthetic address.
// Keep the exception tied to both the explicit hostname and private-network opt-in;
// other hosts and the rest of the reserved 0/8 range must remain blocked.
export function allowedDockerHostAddress(
  normalizedAddress: string,
  hostname: string,
  allowPrivate: boolean,
): boolean {
  return (
    allowPrivate && hostname === "host.docker.internal" && normalizedAddress === "0.250.250.254"
  );
}
