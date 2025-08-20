import { env } from "$env/dynamic/private";

/**
 * Get close matches for a string from a list of options
 * Simple implementation of string similarity matching
 */
function getCloseMatches(word: string, possibilities: string[], cutoff: number = 0.6): string[] {
  const matches: Array<{word: string, ratio: number}> = [];
  
  for (const possibility of possibilities) {
    const ratio = getSimilarity(word.toLowerCase(), possibility.toLowerCase());
    if (ratio >= cutoff) {
      matches.push({word: possibility, ratio});
    }
  }
  
  return matches
    .sort((a, b) => b.ratio - a.ratio)
    .slice(0, 3)
    .map(m => m.word);
}

/**
 * Calculate string similarity ratio (simple implementation)
 */
function getSimilarity(str1: string, str2: string): number {
  const longer = str1.length > str2.length ? str1 : str2;
  const shorter = str1.length > str2.length ? str2 : str1;
  
  if (longer.length === 0) {
    return 1.0;
  }
  
  const editDistance = getEditDistance(longer, shorter);
  return (longer.length - editDistance) / longer.length;
}

/**
 * Calculate edit distance between two strings
 */
function getEditDistance(str1: string, str2: string): number {
  const matrix = Array(str2.length + 1).fill(null).map(() => Array(str1.length + 1).fill(null));
  
  for (let i = 0; i <= str1.length; i++) {
    matrix[0][i] = i;
  }
  
  for (let j = 0; j <= str2.length; j++) {
    matrix[j][0] = j;
  }
  
  for (let j = 1; j <= str2.length; j++) {
    for (let i = 1; i <= str1.length; i++) {
      if (str1[i - 1] === str2[j - 1]) {
        matrix[j][i] = matrix[j - 1][i - 1];
      } else {
        matrix[j][i] = Math.min(
          matrix[j - 1][i - 1] + 1,
          matrix[j][i - 1] + 1,
          matrix[j - 1][i] + 1
        );
      }
    }
  }
  
  return matrix[str2.length][str1.length];
}

/**
 * Configuration validation result interface
 */
export interface ConfigValidationResult {
  errors: string[];
  warnings: string[];
  unknown_vars: string[];
  features: Record<string, any>;
}

/**
 * Check if a configuration value is properly set.
 * 
 * @param value - The configuration value to check
 * @returns boolean indicating if the configuration is properly set
 */
function isConfigured(value: unknown): boolean {
  if (typeof value !== "string") {
    return false;
  }
  return value.trim().length > 0;
}

/**
 * Validate URL format for URL configurations.
 * 
 * @param url - The URL string to validate
 * @returns boolean indicating if the URL is valid
 */
function isValidUrl(url: string): boolean {
  try {
    new URL(url);
    return true;
  } catch {
    return false;
  }
}

/**
 * Detect unknown environment variables that might be typos.
 * Focuses on frontend-specific variables.
 */
function detectUnknownVariables(): string[] {
  const knownFrontendVars = new Set([
    // Core frontend config
    'INTRIC_BACKEND_URL',
    'INTRIC_BACKEND_SERVER_URL', 
    'INTRIC_SYS_API_KEY',
    'JWT_SECRET',
    
    // Auth providers
    'MOBILITY_GUARD_AUTH',
    'MOBILITYGUARD_CLIENT_ID',
    'ZITADEL_INSTANCE_URL',
    'ZITADEL_PROJECT_CLIENT_ID',
    'FORCE_LEGACY_AUTH',
    
    // UI Feature flags
    'SHOW_TEMPLATES',
    'SHOW_WEB_SEARCH', 
    'SHOW_HELP_CENTER',
    
    // External services
    'FEEDBACK_FORM_URL',
    'REQUEST_INTEGRATION_FORM_URL',
    'HELP_CENTER_URL',
    'SUPPORT_EMAIL',
    'SALES_EMAIL',
    
    // System vars to ignore
    'NODE_ENV',
    'PATH',
    'HOME',
    'USER',
    'PWD',
    'OLDPWD'
  ]);
  
  const unknown: string[] = [];
  
  // Check process.env if available (Node.js context)
  if (typeof process !== 'undefined' && process.env) {
    for (const [key] of Object.entries(process.env)) {
      // Skip system variables and common non-config vars
      if (key.startsWith('_') || key.startsWith('npm_') || key.startsWith('LANG') || key.startsWith('LC_')) {
        continue;
      }
      
      // Skip development tool environment variables
      if (key.startsWith('VSCODE_') || key.startsWith('REMOTE_CONTAINERS') || key.startsWith('NVM_') || 
          key.startsWith('PIPX_') || key.startsWith('GIT_') || key.startsWith('PYTHON_')) {
        continue;
      }
      
      // Skip common system/shell variables
      const commonSystemVars = new Set([
        'COLORTERM', 'HOSTNAME', 'VIRTUAL_ENV', 'WAYLAND_DISPLAY', 'GPG_KEY', 
        'LS_COLORS', 'DISPLAY', 'SHLVL', 'PROMPT_DIRTRIM', 'XDG_RUNTIME_DIR',
        'BROWSER', 'EDITOR', 'PAGER', 'MANPATH', 'INFOPATH', 'TERM', 'SHELL',
        'PWD', 'OLDPWD', 'TZ'
      ]);
      if (commonSystemVars.has(key)) {
        continue;
      }
      
      if (!knownFrontendVars.has(key)) {
        unknown.push(key);
      }
    }
  }
  
  return unknown.slice(0, 10); // Limit to prevent spam
}

/**
 * Get configuration status with validation results.
 * This function checks frontend configuration consistency and returns
 * structured results for errors, warnings, and feature detection.
 * 
 * @returns ConfigValidationResult object with validation results
 */
export function getConfigStatus(): ConfigValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const unknown_vars: string[] = [];
  const features: Record<string, any> = {};
  
  // Detect unknown environment variables
  const detectedUnknown = detectUnknownVariables();
  unknown_vars.push(...detectedUnknown);

  // Required configuration checks
  if (!isConfigured(env.INTRIC_BACKEND_URL)) {
    errors.push("INTRIC_BACKEND_URL is required but not configured");
  } else if (!isValidUrl(env.INTRIC_BACKEND_URL!)) {
    warnings.push("INTRIC_BACKEND_URL appears to be an invalid URL format");
  }

  if (!isConfigured(env.JWT_SECRET)) {
    errors.push("JWT_SECRET is required but not configured");
  }

  // Authentication provider validation
  const mobilityGuardUrl = env.MOBILITY_GUARD_AUTH;
  const mobilityGuardClientId = env.MOBILITYGUARD_CLIENT_ID;
  const zitadelUrl = env.ZITADEL_INSTANCE_URL;
  const zitadelClientId = env.ZITADEL_PROJECT_CLIENT_ID;

  // MobilityGuard configuration consistency
  const mobilityGuardConfigs = [mobilityGuardUrl, mobilityGuardClientId].filter(Boolean);
  if (mobilityGuardConfigs.length > 0 && mobilityGuardConfigs.length < 2) {
    warnings.push("MobilityGuard partially configured - both MOBILITY_GUARD_AUTH and MOBILITYGUARD_CLIENT_ID are required");
  }

  // Zitadel configuration consistency
  const zitadelConfigs = [zitadelUrl, zitadelClientId].filter(Boolean);
  if (zitadelConfigs.length > 0 && zitadelConfigs.length < 2) {
    warnings.push("Zitadel partially configured - both ZITADEL_INSTANCE_URL and ZITADEL_PROJECT_CLIENT_ID are required");
  }

  // URL validation for optional configurations
  if (isConfigured(mobilityGuardUrl) && !isValidUrl(mobilityGuardUrl!)) {
    warnings.push("MOBILITY_GUARD_AUTH appears to be an invalid URL format");
  }

  if (isConfigured(zitadelUrl) && !isValidUrl(zitadelUrl!)) {
    warnings.push("ZITADEL_INSTANCE_URL appears to be an invalid URL format");
  }

  if (isConfigured(env.INTRIC_BACKEND_SERVER_URL) && !isValidUrl(env.INTRIC_BACKEND_SERVER_URL!)) {
    warnings.push("INTRIC_BACKEND_SERVER_URL appears to be an invalid URL format");
  }

  // Check for configuration conflicts
  if (isConfigured(env.FORCE_LEGACY_AUTH) && env.FORCE_LEGACY_AUTH?.toLowerCase() === 'true') {
    if (zitadelConfigs.length === 2) {
      warnings.push("FORCE_LEGACY_AUTH is enabled but Zitadel is fully configured - legacy auth will take precedence");
    }
  }

  // Feature detection
  features.auth_providers = {
    mobilityguard: mobilityGuardConfigs.length === 2,
    zitadel: zitadelConfigs.length === 2,
    legacy_forced: env.FORCE_LEGACY_AUTH?.toLowerCase() === 'true'
  };

  features.ui_features = {
    show_templates: env.SHOW_TEMPLATES?.toLowerCase() === 'true',
    show_web_search: env.SHOW_WEB_SEARCH?.toLowerCase() === 'true',
    show_help_center: env.SHOW_HELP_CENTER?.toLowerCase() === 'true'
  };

  features.external_services = {
    help_center: isConfigured(env.HELP_CENTER_URL),
    feedback_form: isConfigured(env.FEEDBACK_FORM_URL),
    integration_request_form: isConfigured(env.REQUEST_INTEGRATION_FORM_URL),
    custom_support_email: isConfigured(env.SUPPORT_EMAIL),
    custom_sales_email: isConfigured(env.SALES_EMAIL)
  };

  features.backend_configuration = {
    backend_url: env.INTRIC_BACKEND_URL || 'Not configured',
    server_backend_url: isConfigured(env.INTRIC_BACKEND_SERVER_URL) ? 'Configured' : 'Using same as client URL',
    has_system_api_key: isConfigured(env.INTRIC_SYS_API_KEY)
  };

  return {
    errors,
    warnings,
    unknown_vars,
    features
  };
}

/**
 * Get a configuration summary for logging and debugging.
 * This masks any sensitive information and provides a safe overview
 * of the current configuration state.
 * 
 * @returns Object with configuration summary
 */
export function getConfigSummary(): Record<string, any> {
  const status = getConfigStatus();
  
  return {
    validation: {
      errors_count: status.errors.length,
      warnings_count: status.warnings.length,
      unknown_count: status.unknown_vars.length,
      has_errors: status.errors.length > 0,
      errors: status.errors,
      warnings: status.warnings,
      unknown_vars: status.unknown_vars
    },
    auth_providers: status.features.auth_providers,
    ui_features: status.features.ui_features,
    external_services: status.features.external_services,
    backend_configuration: status.features.backend_configuration,
    backend_configured: Boolean(env.INTRIC_BACKEND_URL)
  };
}

/**
 * Display a minimal configuration summary in the terminal.
 * Focused on essential information only - no spam.
 */
export function displayConfigSummary(): void {
  const summary = getConfigSummary();
  
  console.log("─".repeat(50));
  console.log("🌐 ENEO Frontend Configuration");
  console.log("─".repeat(50));
  
  // Essential info only
  console.log(`Backend: ${summary.backend_configuration.backend_url || 'Not configured'}`);
  
  // Auth providers (minimal)
  const authProviders = summary.auth_providers;
  const authConfigured = Object.values(authProviders).filter(Boolean).length;
  const authTotal = Object.keys(authProviders).length;
  console.log(`Auth: ${authConfigured}/${authTotal} configured`);
  
  // UI Features (minimal) 
  const uiFeatures = summary.ui_features;
  const uiEnabled = Object.values(uiFeatures).filter(Boolean).length;
  const uiTotal = Object.keys(uiFeatures).length;
  console.log(`Features: ${uiEnabled}/${uiTotal} enabled`);
  
  // Only show warnings/errors/unknowns if they exist
  if (summary.validation.warnings_count > 0) {
    console.log(`⚠️  ${summary.validation.warnings_count} warning(s)`);
  }
  
  if (summary.validation.unknown_count > 0) {
    console.log(`❓ ${summary.validation.unknown_count} unknown variable(s)`);
  }
  
  if (summary.validation.errors_count > 0) {
    console.log(`❌ ${summary.validation.errors_count} error(s)`);
  } else {
    console.log("✅ Configuration OK");
  }
  
  console.log("─".repeat(50));
}

/**
 * Validate configuration and throw error if critical issues found.
 * Use this during application startup to ensure required configuration
 * is present before the application starts serving requests.
 * 
 * @param isDevelopment - Whether we're in development mode (warns instead of throwing)
 * @throws Error if critical configuration is missing in production mode
 */
export function validateConfigOrThrow(isDevelopment: boolean = false): void {
  const status = getConfigStatus();
  
  if (status.errors.length > 0) {
    const errorMessage = `Configuration errors found:\n${status.errors.join('\n')}`;
    
    if (isDevelopment) {
      console.warn('⚠️ Configuration validation warnings in development mode:');
      status.errors.forEach(error => console.warn(`  - ${error}`));
      status.warnings.forEach(warning => console.warn(`  - ${warning}`));
    } else {
      throw new Error(errorMessage);
    }
  }
  
  if (status.warnings.length > 0 && isDevelopment) {
    console.warn('⚠️ Configuration warnings:');
    status.warnings.forEach(warning => console.warn(`  - ${warning}`));
  }
}