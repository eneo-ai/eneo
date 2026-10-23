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

/** Runtime opt-in destination; never expose a script URL or embedded credentials. */
export function getNewAppUrl(): string | undefined {
  const value = getEnvValue("NEW_APP_URL");
  if (!value) return undefined;
  try {
    const url = new URL(value);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) {
      return undefined;
    }
    return url.href;
  } catch {
    return undefined;
  }
}

export function getBackendUrl(): string | undefined {
  return getEnvValue("ENEO_BACKEND_URL");
}

export function getBackendServerUrl(): string | undefined {
  return getEnvValue("ENEO_BACKEND_SERVER_URL");
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
    "https://www.eneo.ai/en/external-support-assistant"
  );

  return Object.freeze({
    baseUrl,
    authUrl,
    // feedbackFormUrl,
    integrationRequestFormUrl,
    helpCenterUrl,
    newAppUrl: getNewAppUrl(),
    frontendVersion,
    gitInfo
  });
}
