import { browser } from "$app/environment";

/**
 * Snapshot of the OS reduced-motion preference for transition durations.
 * Guarded on matchMedia existing because jsdom test runs don't implement it.
 */
export function prefersReducedMotion(): boolean {
  return (
    browser &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}
