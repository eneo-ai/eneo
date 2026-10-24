import { useCallback, useSyncExternalStore } from "react";

/**
 * Whether a media query matches, and `null` while that cannot be known: on
 * the server and during hydration. For markup that CSS already lays out per
 * width from the first paint (both variants rendered, the wrong one hidden):
 * once this knows, the hidden variant can go, with no frame in between.
 * Astryx's useMediaQuery answers `false` until it has measured instead.
 */
export function useMediaMatch(query: string): boolean | null {
  // Stable per query, so a re-render does not subscribe again.
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query]
  );
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => null
  );
}
