import type { McpUiStyles } from "@modelcontextprotocol/ext-apps/app-bridge";
import { getLocale } from "$lib/paraglide/runtime";

/**
 * The style variables a view may use to look at home (MCP Apps names), each
 * taken from the Eneo token that plays that part.
 */
const STYLE_VARIABLES: Record<string, string> = {
  "--color-background-primary": "--background-primary",
  "--color-background-secondary": "--background-secondary",
  "--color-background-tertiary": "--background-tertiary",
  "--color-text-primary": "--text-primary",
  "--color-text-secondary": "--text-secondary",
  "--color-text-tertiary": "--text-muted",
  "--color-border-primary": "--border-default",
  "--color-border-secondary": "--border-dimmer",
  "--color-ring-primary": "--accent-default",
  "--font-sans": "--font-sans"
};

function shownTheme(): "light" | "dark" {
  const chosen = document.documentElement.dataset.theme;
  if (chosen === "light" || chosen === "dark") return chosen;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * What a view is told about where it is shown: the theme, the reader's
 * language and time zone, and Eneo's colours and font as they are right now.
 */
export function hostContext() {
  const computed = getComputedStyle(document.documentElement);
  const variables: Record<string, string> = {};
  for (const [name, token] of Object.entries(STYLE_VARIABLES)) {
    const value = computed.getPropertyValue(token).trim();
    if (value) variables[name] = value;
  }
  return {
    theme: shownTheme(),
    styles: { variables: variables as McpUiStyles },
    locale: getLocale(),
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    platform: "web" as const
  };
}
