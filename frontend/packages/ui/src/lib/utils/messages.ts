/**
 * Simple message helper for UI components
 * Uses paraglide messages from Svelte context
 */

import { getContext } from "svelte";

// Context key for paraglide messages
export const MESSAGES_CONTEXT_KEY = Symbol("messages");

// Helper to get messages from paraglide context
export function getUIMessage(key: string, params?: Record<string, unknown>) {
  const m = getContext(MESSAGES_CONTEXT_KEY) as Record<string, any>;
  if (m && m[key]) {
    return params ? m[key](params) : m[key]();
  }
  // If no context or key not found, return the key as fallback
  return key;
}
