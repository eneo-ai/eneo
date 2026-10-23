"use client";

import { createContext, useContext, useLayoutEffect } from "react";

export type ShellContextValue = {
  /** Opens the ⌘K command palette. */
  openPalette: () => void;
  /** Opens the "Skapa yta" dialog (the create-space flow of /spaces/list). */
  openCreateSpace: () => void;
  /**
   * Hides the phone top bar until the returned function is called. Use
   * `useOwnMobileHeader()` rather than calling it directly.
   */
  registerMobileHeader: () => () => void;
};

export const ShellContext = createContext<ShellContextValue | null>(null);

export function useShell(): ShellContextValue {
  const context = useContext(ShellContext);
  if (!context) throw new Error("useShell must be used inside the app shell");
  return context;
}

/**
 * For a page header that replaces the shell's phone top bar (the chat's):
 * the top bar is hidden only while a component calling this is mounted, so a
 * chat that is loading, failed or hit the error boundary still has the menu.
 * The header must then offer the menu itself: a button that dispatches
 * `OPEN_NAV_EVENT` (see `routes.ts`). Does nothing outside the app shell.
 *
 * A layout effect, so the top bar is gone before the header's first paint.
 */
export function useOwnMobileHeader(): void {
  const register = useContext(ShellContext)?.registerMobileHeader;
  useLayoutEffect(() => register?.(), [register]);
}

/** Marks the navigation drawer, the one modal the palette may open over. */
export const DRAWER_MARKER = "data-shell-drawer";

/**
 * Another modal dialog is open (every dialog in the app is a native modal
 * <dialog>). The ⌘K shortcut must not open the palette over it.
 */
export function isOtherDialogOpen(): boolean {
  return document.querySelector(`dialog[open]:not([${DRAWER_MARKER}])`) !== null;
}
