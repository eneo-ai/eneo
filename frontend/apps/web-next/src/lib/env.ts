import { z } from "zod";

const boolFlag = z
  .enum(["true", "false"])
  .default("false")
  .transform((value) => value === "true");

// The browser never calls the backend directly, so there is no NEXT_PUBLIC_*
// backend URL; everything here is server-side configuration.
const envSchema = z.object({
  ENEO_BACKEND_URL: z.url(),
  // Required from Phase 2 (encrypts the session cookie).
  SESSION_SECRET: z.string().min(32).optional(),
  SHOW_HELP_CENTER: boolFlag,
  HELP_CENTER_URL: z.url().optional(),
  REQUEST_INTEGRATION_FORM_URL: z.url().optional()
});

export type Env = z.infer<typeof envSchema>;

export function parseEnv(source: Record<string, string | undefined> = process.env): Env {
  const result = envSchema.safeParse(source);
  if (!result.success) {
    throw new Error(`Invalid environment variables:\n${z.prettifyError(result.error)}`);
  }
  return result.data;
}

export const env = parseEnv();
