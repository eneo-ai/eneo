/**
 * Simple message helper for UI components
 * Uses paraglide messages from Svelte context
 */

import { getContext } from "svelte";

// Context key for paraglide messages
export const MESSAGES_CONTEXT_KEY = Symbol("messages");

// Context key for the active BCP 47 locale tag (e.g. "sv-SE"), used for date/number formatting
export const LOCALE_CONTEXT_KEY = Symbol("locale");

const FALLBACK_LOCALE = "en-US";

// Helper to get messages from paraglide context
export function getUIMessage(key: string, params?: Record<string, unknown>) {
  const m = getContext(MESSAGES_CONTEXT_KEY) as Record<
    string,
    (params?: Record<string, unknown>) => string
  >;
  if (m && m[key]) {
    return params ? m[key](params) : m[key]();
  }
  // If no context or key not found, return the key as fallback
  return key;
}

// Helper to get the active locale tag from context, falling back to en-US
export function getUILocale(): string {
  const locale = getContext(LOCALE_CONTEXT_KEY);
  return typeof locale === "string" && locale ? locale : FALLBACK_LOCALE;
}
