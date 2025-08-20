/**
 * Core configuration validation and utilities.
 * Framework-agnostic functions that can be used by both build-time and runtime contexts.
 * 
 * This module contains the single source of truth for:
 * - Configuration schema and validation rules
 * - Secret masking utilities
 * - Unknown variable detection with typo suggestions
 * - Configuration summary generation
 */

/**
 * Configuration key metadata
 */
export interface ConfigKey {
  key: string;
  required?: boolean;
  isSecret?: boolean;
  deprecated?: string;
  default?: string;
  description?: string;
  validate?: (value: string) => string | null; // return error message or null
}

/**
 * Configuration validation result
 */
export interface ValidationResult {
  errors: string[];
  warnings: string[];
  unknown_vars: string[];
  features: Record<string, any>;
  config_hash?: string;
  timestamp?: string;
}

/**
 * Configuration schema - single source of truth for all frontend environment variables
 */
export const FRONTEND_CONFIG_SCHEMA: ConfigKey[] = [
  // Core backend configuration
  {
    key: 'INTRIC_BACKEND_URL',
    required: true,
    description: 'The base URL of the Eneo backend instance',
    validate: (value) => {
      try {
        new URL(value);
        return null;
      } catch {
        return 'Invalid URL format';
      }
    }
  },
  {
    key: 'INTRIC_BACKEND_SERVER_URL',
    description: 'Backend URL for server-side requests (optional)'
  },
  {
    key: 'INTRIC_SYS_API_KEY',
    isSecret: true,
    description: 'Internal system API key for server-to-server communication'
  },

  // Security and session management
  {
    key: 'JWT_SECRET',
    required: true,
    isSecret: true,
    description: 'Key used to sign cookies from the frontend'
  },

  // Authentication providers
  {
    key: 'MOBILITY_GUARD_AUTH',
    description: 'MobilityGuard authentication URL'
  },
  {
    key: 'MOBILITYGUARD_CLIENT_ID',
    description: 'MobilityGuard client ID'
  },
  {
    key: 'ZITADEL_INSTANCE_URL',
    description: 'Zitadel instance URL for OIDC authentication'
  },
  {
    key: 'ZITADEL_PROJECT_CLIENT_ID',
    description: 'Zitadel project client ID for OIDC authentication'
  },
  {
    key: 'FORCE_LEGACY_AUTH',
    description: 'Force legacy authentication instead of new OIDC'
  },

  // UI Feature flags
  {
    key: 'SHOW_TEMPLATES',
    description: 'Show assistant templates in the UI'
  },
  {
    key: 'SHOW_WEB_SEARCH',
    description: 'Show web search features in the UI'
  },
  {
    key: 'SHOW_HELP_CENTER',
    description: 'Show help center features in the UI'
  },

  // External service URLs
  {
    key: 'FEEDBACK_FORM_URL',
    description: 'URL for feedback form'
  },
  {
    key: 'REQUEST_INTEGRATION_FORM_URL',
    description: 'URL for integration request form'
  },
  {
    key: 'HELP_CENTER_URL',
    description: 'Help center URL'
  },
  {
    key: 'SUPPORT_EMAIL',
    description: 'Support team email address'
  },
  {
    key: 'SALES_EMAIL',
    description: 'Sales team email address'
  }
];

/**
 * Get all known configuration keys
 */
export function getKnownConfigKeys(): Set<string> {
  return new Set(FRONTEND_CONFIG_SCHEMA.map(config => config.key));
}

/**
 * Check if a configuration value is properly set
 */
export function isConfigured(value: string | undefined): boolean {
  return typeof value === 'string' && value.trim().length > 0;
}

/**
 * Mask secret values for safe display
 */
export function maskSecret(value: string | undefined, isSecret: boolean = false): string {
  if (!value) return 'Not set';
  if (!isSecret) return value;
  
  if (value.length < 12) {
    return '****' + '*'.repeat(Math.min(value.length, 4));
  }
  return '****' + value.slice(-4);
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
 * Get close matches for a string from a list of options
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
 * Generate configuration hash for drift detection
 */
export function generateConfigHash(env: Record<string, string | undefined>): string {
  const relevantConfig: Record<string, string> = {};
  
  for (const config of FRONTEND_CONFIG_SCHEMA) {
    const value = env[config.key];
    if (isConfigured(value)) {
      // For secrets, hash the value rather than storing it
      if (config.isSecret) {
        relevantConfig[config.key] = `secret_length_${value!.length}`;
      } else {
        relevantConfig[config.key] = value!;
      }
    }
  }
  
  const configString = JSON.stringify(relevantConfig, Object.keys(relevantConfig).sort());
  
  // Simple hash function (for display purposes, not cryptographic security)
  let hash = 0;
  for (let i = 0; i < configString.length; i++) {
    const char = configString.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash; // Convert to 32-bit integer
  }
  
  return Math.abs(hash).toString(16).padStart(8, '0');
}

/**
 * Validate environment configuration
 */
export function validateEnv(
  env: Record<string, string | undefined>,
  options: { context?: 'runtime' | 'build' } = {}
): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const unknown_vars: string[] = [];
  const features: Record<string, any> = {};
  
  // Validate each configuration key
  for (const config of FRONTEND_CONFIG_SCHEMA) {
    const rawValue = env[config.key];
    const value = rawValue?.trim();
    
    // Check required fields
    if (config.required && !isConfigured(value)) {
      errors.push(`${config.key} is required but not configured`);
      continue;
    }
    
    // Custom validation
    if (isConfigured(value) && config.validate) {
      const validationError = config.validate(value!);
      if (validationError) {
        if (config.required) {
          errors.push(`${config.key}: ${validationError}`);
        } else {
          warnings.push(`${config.key}: ${validationError}`);
        }
      }
    }
    
    // Check deprecated fields
    if (config.deprecated && isConfigured(value)) {
      warnings.push(`${config.key} is deprecated: ${config.deprecated}`);
    }
  }
  
  // Check for configuration consistency
  const mobilityGuardUrl = env.MOBILITY_GUARD_AUTH;
  const mobilityGuardClientId = env.MOBILITYGUARD_CLIENT_ID;
  const zitadelUrl = env.ZITADEL_INSTANCE_URL;
  const zitadelClientId = env.ZITADEL_PROJECT_CLIENT_ID;
  
  // MobilityGuard configuration consistency
  const mobilityGuardConfigs = [mobilityGuardUrl, mobilityGuardClientId].filter(isConfigured);
  if (mobilityGuardConfigs.length > 0 && mobilityGuardConfigs.length < 2) {
    warnings.push('MobilityGuard partially configured - both MOBILITY_GUARD_AUTH and MOBILITYGUARD_CLIENT_ID are required');
  }
  
  // Zitadel configuration consistency
  const zitadelConfigs = [zitadelUrl, zitadelClientId].filter(isConfigured);
  if (zitadelConfigs.length > 0 && zitadelConfigs.length < 2) {
    warnings.push('Zitadel partially configured - both ZITADEL_INSTANCE_URL and ZITADEL_PROJECT_CLIENT_ID are required');
  }
  
  // Check for configuration conflicts
  if (isConfigured(env.FORCE_LEGACY_AUTH) && env.FORCE_LEGACY_AUTH?.toLowerCase() === 'true') {
    if (zitadelConfigs.length === 2) {
      warnings.push('FORCE_LEGACY_AUTH is enabled but Zitadel is fully configured - legacy auth will take precedence');
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
    features,
    config_hash: generateConfigHash(env),
    timestamp: new Date().toISOString()
  };
}

/**
 * Get a configuration summary for logging and debugging
 */
export function getConfigSummary(result: ValidationResult, options: { verbose?: boolean } = {}): Record<string, any> {
  const summary = {
    validation: {
      errors_count: result.errors.length,
      warnings_count: result.warnings.length,
      unknown_count: result.unknown_vars.length,
      has_errors: result.errors.length > 0,
      config_hash: result.config_hash,
      timestamp: result.timestamp
    },
    auth_providers: result.features.auth_providers,
    ui_features: result.features.ui_features,
    external_services: result.features.external_services,
    backend_configuration: result.features.backend_configuration
  };
  
  if (options.verbose || result.errors.length > 0) {
    summary.validation.errors = result.errors;
  }
  
  if (options.verbose || result.warnings.length > 0) {
    summary.validation.warnings = result.warnings;
  }
  
  if (options.verbose || result.unknown_vars.length > 0) {
    summary.validation.unknown_vars = result.unknown_vars;
  }
  
  return summary;
}

/**
 * Format configuration summary for console display
 */
export function formatConfigSummary(result: ValidationResult, options: { context?: 'build' | 'runtime' } = {}): string {
  const lines: string[] = [];
  const contextLabel = options.context === 'build' ? 'Build-time' : 'Runtime';
  
  lines.push('─'.repeat(50));
  lines.push(`🌐 ENEO Frontend Configuration (${contextLabel})`);
  lines.push('─'.repeat(50));
  
  // Essential info
  const backendUrl = result.features.backend_configuration.backend_url;
  lines.push(`Backend: ${backendUrl}`);
  
  // Auth providers summary
  const authProviders = result.features.auth_providers;
  const authConfigured = Object.values(authProviders).filter(Boolean).length;
  const authTotal = Object.keys(authProviders).length;
  lines.push(`Auth: ${authConfigured}/${authTotal} configured`);
  
  // UI Features summary
  const uiFeatures = result.features.ui_features;
  const uiEnabled = Object.values(uiFeatures).filter(Boolean).length;
  const uiTotal = Object.keys(uiFeatures).length;
  lines.push(`Features: ${uiEnabled}/${uiTotal} enabled`);
  
  // Show issues if they exist
  if (result.warnings.length > 0) {
    lines.push(`⚠️  ${result.warnings.length} warning(s)`);
  }
  
  
  if (result.errors.length > 0) {
    lines.push(`❌ ${result.errors.length} error(s)`);
  } else {
    lines.push('✅ Configuration OK');
  }
  
  if (result.config_hash) {
    lines.push(`Hash: ${result.config_hash}`);
  }
  
  lines.push('─'.repeat(50));
  
  return lines.join('\n');
}