import { env } from "$env/dynamic/private";

/**
 * Gets a boolean flag value from environment variables with fallback support.
 *
 * @param key - The environment variable key to check
 * @param defaultValue - The fallback value if the environment variable is not set
 * @returns The boolean flag value
 *
 * @example
 * getFlagFromEnv("SHOW_WEB_SEARCH", true) // returns boolean based on env.SHOW_WEB_SEARCH
 * getFlagFromEnv("DEBUG_MODE", false)    // returns boolean based on env.DEBUG_MODE
 */
function getFlagFromEnv(key: string, defaultValue: boolean): boolean {
  return getFlagValue(env[key], defaultValue);
}

/**
 * Converts a value (typically from environment variables) to a boolean flag.
 *
 * Handles different types of input:
 * - String: Accepts various common boolean representations
 *   True values (case-insensitive): "true", "1", "yes", "on"
 *   False values (case-insensitive): "false", "0", "no", "off"
 * - Boolean: Returns the value directly
 * - Number: Converts to boolean (0 is false, all other numbers are true)
 * - Null/Undefined: Returns the default value
 *
 * @param flag - The value to convert to a boolean
 * @param defaultValue - The value to return when the input is null, undefined,
 *                      empty string, or cannot be converted to a boolean
 * @returns The boolean interpretation of the input value
 *
 * @example
 * getFlagValue("true")        // returns true
 * getFlagValue("YES")         // returns true
 * getFlagValue("0")           // returns false
 * getFlagValue("")           // returns defaultValue
 * getFlagValue(undefined)    // returns defaultValue
 * getFlagValue(1)            // returns true
 * getFlagValue(false)        // returns false
 */
function getFlagValue(flag: unknown, defaultValue: boolean) {
  // Catch both null and undefined with "=="
  if (flag == null) {
    return defaultValue;
  }

  switch (typeof flag) {
    case "string":
      return getStringFalgValue(flag, defaultValue);

    case "boolean":
      return flag;

    case "number":
      return Boolean(flag);

    default:
      return defaultValue;
  }
}

/**
 * Converts environment variable values to boolean flags.
 *
 * Valid "true" values (case-insensitive):
 * - "true", "1", "yes", "on"
 *
 * Valid "false" values (case-insensitive):
 * - "false", "0", "no", "off"
 *
 * Any other values (including empty string) will return the default value.
 *
 * @param flag - The environment variable value
 * @param defaultValue - Value to return for invalid or unset flags
 */
function getStringFalgValue(flag: string, defaultValue: boolean): boolean {
  const normalisedFlag = flag.toLowerCase().trim();

  // Early return for empty string (docker-compose)
  if (normalisedFlag === "") {
    return defaultValue;
  }

  // True values
  const trueValues = new Set(["true", "1", "yes", "on"]);
  if (trueValues.has(normalisedFlag)) {
    return true;
  }

  // False values
  const falseValues = new Set(["false", "0", "no", "off"]);
  if (falseValues.has(normalisedFlag)) {
    return false;
  }

  // Any other value returns default
  return defaultValue;
}

/**
 * Checks if a configuration value is properly set.
 *
 * A configuration is considered set if:
 * - It is not null or undefined
 * - It is not an empty string (common in docker-compose)
 *
 * @param value - The configuration value to check
 * @returns boolean indicating if the configuration is properly set
 *
 * @example
 * isConfigured("https://example.com")  // returns true
 * isConfigured("")                     // returns false
 * isConfigured(undefined)              // returns false
 * isConfigured(null)                   // returns false
 */
function isConfigured(value: unknown): boolean {
  if (typeof value !== "string") {
    return false;
  }
  return value.trim().length > 0;
}

export function getFeatureFlags() {
  // UI Features (enabled by default)
  const showWebSearch = getFlagFromEnv("SHOW_WEB_SEARCH", false);
  const showHelpCenter = getFlagFromEnv("SHOW_HELP_CENTER", false);

  // Auth
  const zitadelConfigured =
    isConfigured(env.ZITADEL_INSTANCE_URL) && isConfigured(env.ZITADEL_PROJECT_CLIENT_ID);
  const forceLegacyAuth = getFlagFromEnv("FORCE_LEGACY_AUTH", false);
  const useNewAuth = zitadelConfigured && !forceLegacyAuth;
  const tenantFederationEnabled = getFlagFromEnv("FEDERATION_PER_TENANT_ENABLED", false);

  // Single-tenant OIDC: OIDC configured but federation per tenant is disabled
  const singleTenantOidcConfigured =
    !tenantFederationEnabled &&
    isConfigured(env.OIDC_DISCOVERY_ENDPOINT) &&
    isConfigured(env.OIDC_CLIENT_ID) &&
    isConfigured(env.OIDC_CLIENT_SECRET);

  return Object.freeze({
    newAuth: useNewAuth,
    showWebSearch,
    showHelpCenter,
    tenantFederationEnabled,
    singleTenantOidcConfigured
  });
}
