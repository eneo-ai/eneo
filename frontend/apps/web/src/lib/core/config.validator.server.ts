import { env } from "$env/dynamic/private";
import { validateEnv, getConfigSummary as getCoreConfigSummary, formatConfigSummary, type ValidationResult } from "$lib/config/core";

/**
 * Configuration validation result interface
 * @deprecated - use ValidationResult from core.ts
 */
export interface ConfigValidationResult {
  errors: string[];
  warnings: string[];
  unknown_vars: string[];
  features: Record<string, any>;
}

/**
 * Get configuration status with validation results.
 * Uses the shared core validation logic with SvelteKit's env context.
 */
export function getConfigStatus(): ValidationResult {
  return validateEnv(env, { context: 'runtime' });
}

/**
 * Get a configuration summary for logging and debugging.
 * Uses the shared core logic with SvelteKit's env context.
 */
export function getConfigSummary(): Record<string, any> {
  const status = getConfigStatus();
  return getCoreConfigSummary(status, { verbose: true });
}

/**
 * Display a minimal configuration summary in the terminal.
 * Uses the shared core formatting logic.
 */
export function displayConfigSummary(): void {
  const status = getConfigStatus();
  console.log(formatConfigSummary(status, { context: 'runtime' }));
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