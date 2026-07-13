import { browser } from "$app/environment";

/**
 * One-shot read of the OS reduced-motion preference for transition durations.
 * This is a mount-time snapshot by contract — Svelte transition params are
 * evaluated per run, but callers store the result once, so a live preference
 * change applies from the next component mount (CSS `@media` rules in the
 * same components DO follow the preference live). Guarded on matchMedia
 * existing because jsdom test runs don't implement it.
 */
export function prefersReducedMotion(): boolean {
  return (
    browser &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}
