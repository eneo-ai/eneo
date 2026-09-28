import { z } from "zod";
import { computeConfigSchema, type ComputeConfig } from "./tools/compute/config";
import { tabularConfigSchema, type TabularConfig } from "./tools/tabular/config";

// Everything comes from the environment: the runtime has no database, no tenant state and no
// operator API. Eneo decides who may call a tool; this process only checks the shared bearer.
const environmentSchema = z.object({
  TOOL_RUNTIME_TOKEN: z
    .string()
    .min(32, "TOOL_RUNTIME_TOKEN must be at least 32 characters (use `openssl rand -hex 32`)"),
  PORT: z.coerce.number().int().min(1).max(65_535).default(3010),
  MAX_CONCURRENCY: z.coerce.number().int().min(1).max(256).default(16),
  COMPUTE_TIMEOUT_MS: z.coerce.number().int().optional(),
  COMPUTE_MEMORY_MB: z.coerce.number().int().optional(),
  // Optional hard limit on where tabular tools may fetch files. Eneo sends its file origin
  // with every call; when this comma-separated list is set, that origin must be on it.
  TOOL_RUNTIME_FILE_ORIGINS: z
    .string()
    .optional()
    .transform((value) =>
      (value ?? "")
        .split(",")
        .map((origin) => origin.trim().replace(/\/$/, ""))
        .filter(Boolean),
    )
    .refine(
      (origins) =>
        origins.every((origin) => {
          try {
            const url = new URL(origin);
            return ["http:", "https:"].includes(url.protocol) && url.origin === origin;
          } catch {
            return false;
          }
        }),
      { message: "TOOL_RUNTIME_FILE_ORIGINS must list origins (scheme, host and port), no paths" },
    ),
  TABULAR_MAX_UPLOAD_MB: z.coerce.number().int().optional(),
  TABULAR_CACHE_MB: z.coerce.number().int().optional(),
  // Native DuckDB children are memory-heavy (up to memory_mb each): run few at a time.
  TABULAR_CONCURRENCY: z.coerce.number().int().min(1).max(16).default(2),
});

export type RuntimeConfig = {
  token: string;
  port: number;
  maxConcurrency: number;
  compute: ComputeConfig;
  tabular: { config: TabularConfig; allowedFileOrigins: string[]; concurrency: number };
};

export function loadConfig(environment: Record<string, string | undefined>): RuntimeConfig {
  const parsed = environmentSchema.parse(environment);
  return {
    token: parsed.TOOL_RUNTIME_TOKEN,
    port: parsed.PORT,
    maxConcurrency: parsed.MAX_CONCURRENCY,
    compute: computeConfigSchema.parse({
      ...(parsed.COMPUTE_TIMEOUT_MS !== undefined ? { timeout_ms: parsed.COMPUTE_TIMEOUT_MS } : {}),
      ...(parsed.COMPUTE_MEMORY_MB !== undefined ? { memory_mb: parsed.COMPUTE_MEMORY_MB } : {}),
    }),
    tabular: {
      allowedFileOrigins: parsed.TOOL_RUNTIME_FILE_ORIGINS,
      concurrency: parsed.TABULAR_CONCURRENCY,
      config: tabularConfigSchema.parse({
        ...(parsed.TABULAR_MAX_UPLOAD_MB !== undefined
          ? { max_upload_bytes: parsed.TABULAR_MAX_UPLOAD_MB * 1024 * 1024 }
          : {}),
        ...(parsed.TABULAR_CACHE_MB !== undefined
          ? { cache_max_bytes: parsed.TABULAR_CACHE_MB * 1024 * 1024 }
          : {}),
      }),
    },
  };
}
