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

/** Match the current viewport immediately and follow changes.
 * Astryx's useMediaQuery returns false until its effect measures the viewport.
 */
export function useMediaMatch(query: string): boolean {
  // Stable per query, so a re-render does not subscribe again.
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query]
  );
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches);
}
