import { z } from "zod";
import { computeConfigSchema, type ComputeConfig } from "./tools/compute/config";

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
});

export type RuntimeConfig = {
  token: string;
  port: number;
  maxConcurrency: number;
  compute: ComputeConfig;
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
  };
}
