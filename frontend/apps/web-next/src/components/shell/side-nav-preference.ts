/**
 * Whether the desktop SideNav is collapsed to its icon rail: a per-browser
 * cookie preference, read on first mount and updated by the SideNav.
 *
 * SideNav's resizable.autoSaveId would also add a drag-to-resize handle;
 * this preference controls only the icon rail toggle.
 */

export const SIDE_NAV_COLLAPSED_COOKIE = "eneo_sidenav_collapsed";

const ONE_YEAR_IN_SECONDS = 60 * 60 * 24 * 365;

/** The stored preference; anything but "1" (including no cookie) is expanded. */
export function isSideNavCollapsed(cookieValue: string | undefined): boolean {
  return cookieValue === "1";
}

/** Read before the SPA's first shell render, using the server's value parser. */
export function readSideNavCollapsedCookie(cookie = document.cookie): boolean {
  const value = cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${SIDE_NAV_COLLAPSED_COOKIE}=`))
    ?.slice(SIDE_NAV_COLLAPSED_COOKIE.length + 1);
  return isSideNavCollapsed(value);
}

/** Remembers the choice in this browser. */
export function storeSideNavCollapsed(collapsed: boolean): void {
  const secure = window.location.protocol === "https:" ? "; secure" : "";
  document.cookie = `${SIDE_NAV_COLLAPSED_COOKIE}=${collapsed ? "1" : "0"}; path=/; max-age=${ONE_YEAR_IN_SECONDS}; samesite=lax${secure}`;
}
