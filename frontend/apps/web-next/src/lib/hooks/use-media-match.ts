import { MEDIA } from "@/lib/breakpoints";
import { useCallback, useSyncExternalStore } from "react";

/**
 * A phone (decision 1: below 768 px, Tailwind `md`): a space is a pushed
 * screen with content tabs, collections are list rows.
 */
export const PHONE_QUERY = `not all and ${MEDIA.md}`;

/**
 * The drawer's layouts (decision 1: below 1024 px, Tailwind `lg`; a phone, an
 * iPad held upright): pushed screens have a PageBar, Konto is a page.
 */
export const MOBILE_QUERY = `not all and ${MEDIA.lg}`;

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
