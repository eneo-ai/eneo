/**
 * Startup check for the variables the web app needs to reach the backend, and
 * for renamed, removed or deprecated ones that are still set.
 *
 * Without it a missing backend URL only shows up at request time: login posts
 * to `undefined/api/...`, gets a 404 from the web app itself, and the user
 * sees "Incorrect credentials".
 */

const UPGRADE_GUIDE_URL = "https://docs.eneo.ai/v2.2/guides/upgrade-2-2-0";
const DEPLOYMENT_GUIDE_URL =
  "https://docs.eneo.ai/v2.2/guides/deployment#environment-configuration";
const OIDC_MIGRATION_GUIDE_URL =
  "https://docs.eneo.ai/guides/oidc-federation#migrate-from-the-mobilityguard-settings";
const ZITADEL_MIGRATION_GUIDE_URL =
  "https://docs.eneo.ai/guides/oidc-federation#migrate-from-the-zitadel-settings";

const RENAMED_VARIABLES = [
  { removed: "INTRIC_BACKEND_URL", replacement: "ENEO_BACKEND_URL" },
  { removed: "INTRIC_BACKEND_SERVER_URL", replacement: "ENEO_BACKEND_SERVER_URL" },
  { removed: "PUBLIC_INTRIC_BACKEND_URL", replacement: "PUBLIC_ENEO_BACKEND_URL" }
] as const;

/** Fed the removed MobilityGuard login; sign-in now uses the backend's OIDC_* settings. */
const REMOVED_SIGN_IN_VARIABLES = ["MOBILITY_GUARD_AUTH", "MOBILITYGUARD_CLIENT_ID"] as const;

/** Turn on the provider-bound Zitadel sign-in, which the next release removes. */
const DEPRECATED_SIGN_IN_VARIABLES = ["ZITADEL_INSTANCE_URL", "ZITADEL_PROJECT_CLIENT_ID"] as const;

type Env = Record<string, string | undefined>;

function isSet(env: Env, name: string): boolean {
  const value = env[name];
  return value != null && value.trim() !== "";
}

export function inspectDeploymentEnv(env: Env): { errors: string[]; warnings: string[] } {
  const errors: string[] = [];
  const warnings: string[] = [];

  for (const { removed, replacement } of RENAMED_VARIABLES) {
    if (!isSet(env, removed)) continue;
    if (isSet(env, replacement)) {
      warnings.push(`${removed} is ignored because ${replacement} is set. Remove ${removed}.`);
    } else {
      errors.push(
        `${removed} is no longer read (removed in Eneo 2.2). Rename it to ${replacement}. See ${UPGRADE_GUIDE_URL}`
      );
    }
  }

  for (const name of REMOVED_SIGN_IN_VARIABLES) {
    if (!isSet(env, name)) continue;
    warnings.push(
      `${name} is no longer used for sign-in. Set the OIDC_* variables in the backend and remove ${name}. See ${OIDC_MIGRATION_GUIDE_URL}`
    );
  }

  const zitadelVariables = DEPRECATED_SIGN_IN_VARIABLES.filter((name) => isSet(env, name));
  if (zitadelVariables.length > 0) {
    warnings.push(
      `The Zitadel sign-in (${zitadelVariables.join(", ")}) is deprecated and will be removed in the next release. Register Zitadel in the backend's OIDC_DISCOVERY_ENDPOINT, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET, then remove the ZITADEL_* variables. See ${ZITADEL_MIGRATION_GUIDE_URL}`
    );
  }

  if (!isSet(env, "ENEO_BACKEND_URL") && !isSet(env, "INTRIC_BACKEND_URL")) {
    errors.push(
      `ENEO_BACKEND_URL is not set. The web app needs it to reach the backend. See ${DEPLOYMENT_GUIDE_URL}`
    );
  }

  return { errors, warnings };
}

/** Throws when the web app cannot reach the backend with this environment. */
export function assertDeploymentEnv(env: Env, warn: (message: string) => void = console.warn) {
  const { errors, warnings } = inspectDeploymentEnv(env);
  for (const warning of warnings) warn(warning);
  if (errors.length > 0) {
    throw new Error(`The web app cannot start with this environment:\n  ${errors.join("\n  ")}`);
  }
}
