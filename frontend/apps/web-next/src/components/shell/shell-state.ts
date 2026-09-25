"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * localStorage that never throws: private windows, blocked site data and
 * quota errors all make the accessors throw, and a preference must never take
 * the shell down with it. Values only live in this browser.
 */
export const safeStorage = {
  get(key: string): string | null {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key: string, value: string): boolean {
    try {
      window.localStorage.setItem(key, value);
      return true;
    } catch {
      return false;
    }
  }
};

export const SIDE_NAV_COLLAPSED_KEY = "eneo.sidenav.collapsed";

const collapsedListeners = new Set<() => void>();
// Session fallback when storage is unavailable; null means "read storage".
let collapsedOverride: boolean | null = null;

function readCollapsed(): boolean {
  return collapsedOverride ?? safeStorage.get(SIDE_NAV_COLLAPSED_KEY) === "1";
}

function subscribeCollapsed(listener: () => void) {
  collapsedListeners.add(listener);
  // Another tab changed the preference: follow it.
  const onStorage = (event: StorageEvent) => {
    if (event.key !== SIDE_NAV_COLLAPSED_KEY) return;
    collapsedOverride = null;
    listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    collapsedListeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function setSideNavCollapsed(collapsed: boolean) {
  collapsedOverride = safeStorage.set(SIDE_NAV_COLLAPSED_KEY, collapsed ? "1" : "0")
    ? null
    : collapsed;
  collapsedListeners.forEach((listener) => listener());
}

/** Test hook: forget the in-memory fallback between tests. */
export function resetSideNavCollapsedForTest() {
  collapsedOverride = null;
}

/**
 * Whether the desktop SideNav is collapsed to its icon rail. The server (and
 * the hydration render) always sees the expanded nav; a stored preference
 * applies right after hydration.
 */
export function useSideNavCollapsed(): [boolean, (collapsed: boolean) => void] {
  const collapsed = useSyncExternalStore(subscribeCollapsed, readCollapsed, () => false);
  const set = useCallback((next: boolean) => setSideNavCollapsed(next), []);
  return [collapsed, set];
}

/** Below Tailwind's `md` breakpoint: the SideNav becomes a drawer. */
export const MOBILE_QUERY = "(width < 48rem)";

function subscribeMobile(listener: () => void) {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(MOBILE_QUERY);
  query.addEventListener?.("change", listener);
  return () => query.removeEventListener?.("change", listener);
}

/** Whether the viewport is phone-width right now (browser only). */
export function isMobileViewport(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(MOBILE_QUERY).matches;
}

/** True on phone-width layouts; false on the server and during hydration. */
export function useIsMobile(): boolean {
  return useSyncExternalStore(subscribeMobile, isMobileViewport, () => false);
}
