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
 * Get environment configuration values.
 *
 * __IMPORTANT__: ALL these values will be exposed to the client! So be careful what you add here.
 *
 * @returns Object with all environment configuration values
 */
export function getEnvironmentConfig() {
  const baseUrl = getEnvValue("INTRIC_BACKEND_URL");
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
