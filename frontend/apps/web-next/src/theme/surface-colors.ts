import { eneoTheme } from "./eneo";

/**
 * The page surface's colour in light and dark mode, read from the built theme
 * (`--color-background-surface`, eneo-theme.ts): what the browser paints
 * behind its status bar and toolbar, so they continue the top bar.
 */
export function surfaceColors(): { light: string; dark: string } {
  const value = eneoTheme.tokens["--color-background-surface"] ?? "";
  const match = /^light-dark\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)$/.exec(value);
  return match ? { light: match[1]!, dark: match[2]! } : { light: value, dark: value };
}
