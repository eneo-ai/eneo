import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * `false` on the server and during the hydration render, `true` afterwards.
 * Use it to switch to client-only values (localStorage, matchMedia, next-themes'
 * resolvedTheme) without a hydration mismatch and without effect + setState.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false
  );
}
