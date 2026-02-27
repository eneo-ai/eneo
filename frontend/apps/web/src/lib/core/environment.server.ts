import { env } from "$env/dynamic/private";

/**
 * Gets a configuration value from environment variables with fallback support.
 *
 * @param key - The environment variable key to check
 * @param defaultValue - The fallback value if the environment variable is not set
 * @returns The environment value or the default if not set
 *
 * @example
 * getEnvValue("API_URL", "https://api.example.com")  // returns env.API_URL or fallback
 * getEnvValue("OPTIONAL_CONFIG")                     // returns env.OPTIONAL_CONFIG or undefined
 */
function getEnvValue(key: string, defaultValue: string): string;
function getEnvValue(key: string): string | undefined;
function getEnvValue(key: string, defaultValue?: string): string | undefined {
  const value = env[key];

  // Return default for null, undefined or empty strings
  if (value == null || value.trim() === "") {
    return defaultValue;
  }

  return value;
}

/**
 * Read an environment variable with fallback to a legacy name.
 * Logs a one-time deprecation warning if the legacy name is in use.
 */
const _legacyWarned = new Set<string>();

function getEnvWithFallback(newKey: string, legacyKey: string): string | undefined {
  const value = env[newKey];
  if (value != null && value.trim() !== "") return value;

  const legacy = env[legacyKey];
  if (legacy != null && legacy.trim() !== "") {
    if (!_legacyWarned.has(legacyKey)) {
      console.warn(
        `DEPRECATION: Using ${legacyKey}. Please update to ${newKey}. Legacy vars will be removed in v3.0.`
      );
      _legacyWarned.add(legacyKey);
    }
    return legacy;
  }
  return undefined;
}

/** Resolve backend URL with INTRIC_ legacy fallback. */
export function getBackendUrl(): string | undefined {
  return getEnvWithFallback("ENEO_BACKEND_URL", "INTRIC_BACKEND_URL");
}

/** Resolve backend server URL with INTRIC_ legacy fallback. */
export function getBackendServerUrl(): string | undefined {
  return getEnvWithFallback("ENEO_BACKEND_SERVER_URL", "INTRIC_BACKEND_SERVER_URL");
}

/**
 * Get environment configuration values.
 *
 * __IMPORTANT__: ALL these values will be exposed to the client! So be careful what you add here.
 *
 * @returns Object with all environment configuration values
 */
export function getEnvironmentConfig() {
  const baseUrl = getBackendUrl();
  const authUrl = getEnvValue("ZITADEL_INSTANCE_URL");

  // Version tracking for preview deployments
  const frontendVersion = __FRONTEND_VERSION__;
  const gitInfo = __IS_PREVIEW__
    ? {
        branch: __GIT_BRANCH__ ?? "Branch not found",
        commit: __GIT_COMMIT_SHA__ ?? "Commit not found"
      }
    : undefined;

  // URLS for various functionality
  // const feedbackFormUrl = getEnvValue("FEEDBACK_FORM_URL");
  const integrationRequestFormUrl = getEnvValue("REQUEST_INTEGRATION_FORM_URL");
  const helpCenterUrl = getEnvValue(
    "HELP_CENTER_URL",
    "https://www.intric.ai/en/external-support-assistant"
  );

  return Object.freeze({
    baseUrl,
    authUrl,
    // feedbackFormUrl,
    integrationRequestFormUrl,
    helpCenterUrl,
    frontendVersion,
    gitInfo,
  });
}
