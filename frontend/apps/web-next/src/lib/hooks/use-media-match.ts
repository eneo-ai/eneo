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
 * A phone in a hand, held either way: touched, and either narrower than a phone (below 768 px) or
 * as short as one held sideways (a phone turned is 844 px wide and under 430 px tall; an iPad is
 * 1024 px or more wide when it is short with its keyboard up). Turning it does not change which
 * it is, so a screen built for a phone stays one and keeps what is open on it.
 */
export const HANDHELD_QUERY =
  "(pointer: coarse) and (width < 48rem), (pointer: coarse) and (height < 31.25rem) and (width < 64rem)";

/**
 * A phone's layout: narrower than a phone, or a phone in a hand held sideways. A screen built for a
 * phone with this stays built for one when the phone is turned, and keeps what is open on it.
 */
export function usePhoneScreen(): boolean {
  const narrow = useMediaMatch(PHONE_QUERY);
  const handheld = useMediaMatch(HANDHELD_QUERY);
  return narrow || handheld;
}

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
