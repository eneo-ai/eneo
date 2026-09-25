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

function setSideNavCollapsed(collapsed: boolean) {
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
 *
 * Not SideNav's own `resizable.autoSaveId` persistence: that also adds a
 * drag-to-resize handle the design does not have, and a width that can only
 * be set by dragging would need a single-pointer alternative (WCAG 2.5.7).
 */
export function useSideNavCollapsed(): [boolean, (collapsed: boolean) => void] {
  const collapsed = useSyncExternalStore(subscribeCollapsed, readCollapsed, () => false);
  const set = useCallback((next: boolean) => setSideNavCollapsed(next), []);
  return [collapsed, set];
}
