/**
 * Whether the desktop SideNav is collapsed to its icon rail: a per-browser
 * preference in a cookie, so the server renders the nav the way the user left
 * it (no layout jump after hydration). Plain module on purpose: the server
 * layout reads the cookie name and parser, the SideNav writes the cookie.
 *
 * Not SideNav's own `resizable.autoSaveId` persistence: that lives in
 * localStorage (only readable after hydration) and also adds a drag-to-resize
 * handle the design does not have, whose width could only be set by dragging
 * (WCAG 2.5.7).
 */

export const SIDE_NAV_COLLAPSED_COOKIE = "eneo_sidenav_collapsed";

const ONE_YEAR_IN_SECONDS = 60 * 60 * 24 * 365;

/** The stored preference; anything but "1" (including no cookie) is expanded. */
export function isSideNavCollapsed(cookieValue: string | undefined): boolean {
  return cookieValue === "1";
}

/** Remembers the choice in this browser. */
export function storeSideNavCollapsed(collapsed: boolean): void {
  const secure = window.location.protocol === "https:" ? "; secure" : "";
  document.cookie = `${SIDE_NAV_COLLAPSED_COOKIE}=${collapsed ? "1" : "0"}; path=/; max-age=${ONE_YEAR_IN_SECONDS}; samesite=lax${secure}`;
}
