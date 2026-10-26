import { z } from "zod";
import { computeConfigSchema, type ComputeConfig } from "./tools/compute/config";
import { tabularConfigSchema, type TabularConfig } from "./tools/tabular/config";
import { documentConfigSchema, type DocumentConfig } from "./tools/documents/config";
import { forecastConfigSchema, type ForecastConfig } from "./tools/forecast/config";

// Everything comes from the environment: the runtime has no database, no tenant state and no
// operator API. Eneo decides who may call a tool; this process only checks the shared bearer.
/** An empty value (`FORECAST_MODEL_NAME=` from a Compose default) means unset, not invalid. */
const unsetIfEmpty = <T extends z.ZodType>(schema: T) =>
  z.preprocess((value) => (value === "" ? undefined : value), schema);

const environmentSchema = z.object({
  TOOL_RUNTIME_TOKEN: z
    .string()
    .min(32, "TOOL_RUNTIME_TOKEN must be at least 32 characters (use `openssl rand -hex 32`)"),
  PORT: z.coerce.number().int().min(1).max(65_535).default(3010),
  MAX_CONCURRENCY: z.coerce.number().int().min(1).max(256).default(16),
  MAX_QUEUE: z.coerce.number().int().min(0).max(256).default(32),
  MAX_QUEUE_PER_GROUP: z.coerce.number().int().min(0).max(256).default(8),
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
  // How long parsed sheets stay on disk. The floor keeps an entry alive for the call that
  // built it: the query child reads its sheets after the parse.
  TABULAR_CACHE_TTL_SECONDS: z.coerce.number().int().min(60).max(86_400).optional(),
  // Native DuckDB children are memory-heavy (up to memory_mb each): run few at a time.
  TABULAR_CONCURRENCY: z.coerce.number().int().min(1).max(16).default(2),
  // Refuse to start, and to run any job, unless sandbox children are confined with Landlock.
  TOOL_RUNTIME_REQUIRE_CONFINEMENT: z
    .enum(["true", "false"])
    .default("false")
    .transform((value) => value === "true"),
  // Shown in the footer of generated documents.
  DOCUMENT_ORGANISATION_NAME: z.string().max(120).optional(),
  // Markdown characters a document may hold; the request body cap follows it.
  DOCUMENT_MAX_CONTENT_CHARS: z.coerce.number().int().min(5000).max(1_000_000).optional(),
  // PDF renders run a Python sidecar each, a few hundred MB apiece: run few at a time.
  DOCUMENT_PDF_CONCURRENCY: z.coerce.number().int().min(1).max(8).default(2),
  // A forecast checkpoint (config.json + model.safetensors) the operator mounted read-only.
  // The runtime ships no weights: the operator chooses a model they may use.
  FORECAST_MODEL_PATH: unsetIfEmpty(z.string().min(1).default("/models/forecast")),
  // How the model is named to users, for example "Timestral 28M".
  FORECAST_MODEL_NAME: unsetIfEmpty(z.string().min(1).max(80).optional()),
  // Each forecast runs a Python sidecar with torch, several hundred MB: run few at a time.
  FORECAST_CONCURRENCY: z.coerce.number().int().min(1).max(4).default(1),
  FORECAST_THREADS: z.coerce.number().int().min(1).max(16).default(2),
});

export type RuntimeConfig = {
  token: string;
  port: number;
  maxConcurrency: number;
  maxQueue: number;
  maxQueuePerGroup: number;
  requireConfinement: boolean;
  compute: ComputeConfig;
  tabular: { config: TabularConfig; allowedFileOrigins: string[]; concurrency: number };
  documents: DocumentConfig;
  pdfConcurrency: number;
  forecast: ForecastConfig;
  forecastConcurrency: number;
  /** Request bodies up to this size; room for the largest document, JSON-escaped. */
  maxBodyBytes: number;
};

export function loadConfig(environment: Record<string, string | undefined>): RuntimeConfig {
  const parsed = environmentSchema.parse(environment);
  return {
    token: parsed.TOOL_RUNTIME_TOKEN,
    port: parsed.PORT,
    maxConcurrency: parsed.MAX_CONCURRENCY,
    maxQueue: parsed.MAX_QUEUE,
    maxQueuePerGroup: parsed.MAX_QUEUE_PER_GROUP,
    requireConfinement: parsed.TOOL_RUNTIME_REQUIRE_CONFINEMENT,
    compute: computeConfigSchema.parse({
      ...(parsed.COMPUTE_TIMEOUT_MS !== undefined ? { timeout_ms: parsed.COMPUTE_TIMEOUT_MS } : {}),
      ...(parsed.COMPUTE_MEMORY_MB !== undefined ? { memory_mb: parsed.COMPUTE_MEMORY_MB } : {}),
    }),
    documents: documentConfigSchema.parse({
      ...(parsed.DOCUMENT_ORGANISATION_NAME
        ? { organisation_name: parsed.DOCUMENT_ORGANISATION_NAME }
        : {}),
      ...(parsed.DOCUMENT_MAX_CONTENT_CHARS !== undefined
        ? { max_content_chars: parsed.DOCUMENT_MAX_CONTENT_CHARS }
        : {}),
    }),
    pdfConcurrency: parsed.DOCUMENT_PDF_CONCURRENCY,
    forecast: forecastConfigSchema.parse({
      model_path: parsed.FORECAST_MODEL_PATH,
      ...(parsed.FORECAST_MODEL_NAME ? { model_name: parsed.FORECAST_MODEL_NAME } : {}),
      threads: parsed.FORECAST_THREADS,
    }),
    forecastConcurrency: parsed.FORECAST_CONCURRENCY,
    // Swedish text escapes to at most a few bytes per character; images travel by reference.
    maxBodyBytes: Math.max(
      256 * 1024,
      (parsed.DOCUMENT_MAX_CONTENT_CHARS ?? 50_000) * 4 + 64 * 1024,
    ),
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
        ...(parsed.TABULAR_CACHE_TTL_SECONDS !== undefined
          ? { cache_ttl_ms: parsed.TABULAR_CACHE_TTL_SECONDS * 1000 }
          : {}),
      }),
    },
  };
}
