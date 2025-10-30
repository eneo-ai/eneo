/**
 * Simple logger utility that adds timestamps to console output
 */

function timestamp(): string {
  return new Date().toISOString();
}

export const logger = {
  log: (...args: any[]) => {
    console.log(`[${timestamp()}]`, ...args);
  },
  error: (...args: any[]) => {
    console.error(`[${timestamp()}]`, ...args);
  },
  warn: (...args: any[]) => {
    console.warn(`[${timestamp()}]`, ...args);
  },
  debug: (...args: any[]) => {
    console.log(`[${timestamp()}] [DEBUG]`, ...args);
  }
};
