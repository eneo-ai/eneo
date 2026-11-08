import { useMediaQuery } from "@astryxdesign/core/hooks";
import { MEDIA } from "@/lib/breakpoints";

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
 * it is, so a screen built for a phone stays one and keeps what is open on it. Not Astryx's
 * compactDefinition, which counts any window under 500 px tall: a short desktop window or an iPad
 * with its keyboard up is not a phone here, and rem follows the font size as Tailwind does.
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
  return useMediaQuery(PHONE_SCREEN_QUERY);
}

/**
 * A tablet in a hand (an iPad either way): touch, and not a phone's layout. It
 * keeps the shell built for touch (#1328): the full SideNav or its icon rail
 * with every space, a space's header with its tabs, and Konto's tabs. The top
 * bar and the sidebar that holds one place are for a computer with a mouse.
 */
export function useTouchTablet(): boolean {
  const coarse = useMediaQuery("(pointer: coarse)");
  const phone = usePhoneScreen();
  return coarse && !phone;
}
