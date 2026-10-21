import type { McpUiHostContext, McpUiStyles } from "@modelcontextprotocol/ext-apps/app-bridge";

/**
 * The style variables a view may use to look at home (MCP Apps names), each
 * taken from the Eneo theme token that plays that part (src/theme/eneo-theme.ts).
 */
const STYLE_VARIABLES: Record<string, string> = {
  "--color-background-primary": "--color-background-surface",
  "--color-background-secondary": "--color-background-muted",
  "--color-background-tertiary": "--eneo-color-background-sunken",
  "--color-text-primary": "--color-text-primary",
  "--color-text-secondary": "--color-text-secondary",
  "--color-text-tertiary": "--eneo-color-text-tertiary",
  "--color-border-primary": "--color-border",
  "--color-border-secondary": "--color-border-emphasized",
  "--color-ring-primary": "--color-accent",
  "--font-sans": "--font-family-body"
};

/** The colour mode in force: next-themes sets `.dark`/`.light` on <html> before first paint. */
export function shownTheme(): "light" | "dark" {
  const root = document.documentElement;
  if (root.classList.contains("dark")) return "dark";
  if (root.classList.contains("light")) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * What a view is told about where it is shown: the theme, the reader's
 * language and time zone, and Eneo's colours and font as they are right now.
 */
export function hostContext(locale: string): McpUiHostContext {
  const computed = getComputedStyle(document.documentElement);
  const variables: Record<string, string> = {};
  for (const [name, token] of Object.entries(STYLE_VARIABLES)) {
    const value = computed.getPropertyValue(token).trim();
    if (value) variables[name] = value;
  }
  return {
    theme: shownTheme(),
    styles: { variables: variables as McpUiStyles },
    locale,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    platform: "web"
  };
}
