import { MEDIA } from "@/lib/breakpoints";
import { useCallback, useSyncExternalStore } from "react";

/**
 * Narrower than 768 px (Tailwind `md`), whatever the pointer. A phone's layout
 * also covers a phone turned sideways: `usePhoneScreen`, `PHONE_SCREEN_QUERY`.
 */
export const PHONE_QUERY = `not all and ${MEDIA.md}`;

/**
 * Compact page layouts below 1024 px (Tailwind `lg`; a phone, an iPad held
 * upright): Konto is a page, and its pushed screens have a PageBar. The shell's
 * drawer is the phone's only (`PHONE_SCREEN_QUERY`).
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
 * A phone's layout: narrower than a phone, or a phone in a hand held sideways. The shell, a
 * space's header and tabs, an editor's index and the collections all switch on it; CSS has it as
 * the `phone:` and `wide:` variants (globals.css; a test keeps them in step).
 */
export const PHONE_SCREEN_QUERY = `${PHONE_QUERY}, ${HANDHELD_QUERY}`;

/**
 * Whether the layout is a phone's (`PHONE_SCREEN_QUERY`). A screen built for a phone with this
 * stays built for one when the phone is turned, and keeps what is open on it.
 */
export function usePhoneScreen(): boolean {
  return useMediaMatch(PHONE_SCREEN_QUERY);
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
