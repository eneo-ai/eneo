import { z } from "zod";

const boolFlag = z
  .enum(["true", "false"])
  .default("false")
  .transform((value) => value === "true");

/**
 * An optional URL the app renders as a link: http(s) only (no javascript:
 * or data: hrefs), and an empty value (`VAR=` in an env file) means unset
 * instead of failing the boot.
 */
const optionalLinkUrl = z.preprocess(
  (value) => (value === "" ? undefined : value),
  z.url({ protocol: /^https?$/ }).optional()
);

// The browser never calls the backend directly, so there is no NEXT_PUBLIC_*
// backend URL; everything here is server-side configuration.
const envSchema = z
  .object({
    ENEO_BACKEND_URL: z.url(),
    // Encrypts the session cookie (any string >= 32 chars).
    SESSION_SECRET: z.string().min(32),
    // Origin the app is reached at; used to build OIDC redirect URIs.
    APP_ORIGIN: z.url().default("http://localhost:3100"),
    // OIDC mode is enabled iff OIDC_ISSUER is set (discovery base URL).
    OIDC_ISSUER: z.url().optional(),
    OIDC_CLIENT_ID: z.string().optional(),
    OIDC_CLIENT_SECRET: z.string().optional(),
    OIDC_SCOPES: z.string().default("openid profile email offline_access"),
    SHOW_WEB_SEARCH: boolFlag,
    SHOW_HELP_CENTER: boolFlag,
    HELP_CENTER_URL: optionalLinkUrl,
    REQUEST_INTEGRATION_FORM_URL: optionalLinkUrl,
    // The deploying organisation's accessibility statement
    // (tillgänglighetsredogörelse, DOS-lagen). Linked from every public page
    // (login, activation, deactivated, login failed) and the profile menu
    // when set; see ACCESSIBILITY.md.
    ACCESSIBILITY_STATEMENT_URL: optionalLinkUrl
  })
  .refine((value) => !value.OIDC_ISSUER || (value.OIDC_CLIENT_ID && value.OIDC_CLIENT_SECRET), {
    message: "OIDC_CLIENT_ID and OIDC_CLIENT_SECRET are required when OIDC_ISSUER is set",
    path: ["OIDC_CLIENT_ID"]
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
