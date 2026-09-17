/**
 * The colour scheme the signed-in app is showing right now: the user's chosen
 * theme, resolved through the system setting when it is "system". Used so
 * previews and the in-app test follow what the admin sees, not the OS alone.
 */
export function currentAppScheme(): "light" | "dark" {
  if (typeof document === "undefined") return "light";
  const chosen = document.documentElement.dataset.theme;
  if (chosen === "light" || chosen === "dark") return chosen;
  return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}
