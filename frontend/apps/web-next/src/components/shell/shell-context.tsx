"use client";

import { createContext, useContext } from "react";

export type ShellContextValue = {
  /** Opens the ⌘K command palette. */
  openPalette: () => void;
  /** Opens the "Skapa yta" dialog (the create-space flow of /spaces/list). */
  openCreateSpace: () => void;
};

export const ShellContext = createContext<ShellContextValue | null>(null);

export function useShell(): ShellContextValue {
  const context = useContext(ShellContext);
  if (!context) throw new Error("useShell must be used inside the app shell");
  return context;
}

/**
 * Spread on a page header that replaces the shell's phone top bar (the
 * chat's, a pushed screen's PageBar). The top bar hides itself in CSS while
 * such a header is on the page (mobile-top-bar.tsx). A chat that is loading
 * or failed still shows the menu. A header that hides
 * the menu must offer it or a way back: a button that dispatches
 * `OPEN_NAV_EVENT` (routes.ts) or a back link.
 */
export const OWN_MOBILE_HEADER = { "data-own-mobile-header": "" } as const;

/**
 * The same, for a header that replaces the top bar on phones only (below
 * 768 px): a space, which tablets show with breadcrumbs under the top bar.
 */
export const OWN_PHONE_HEADER = { "data-own-phone-header": "" } as const;

/** Marks the navigation drawer, the one modal the palette may open over. */
export const DRAWER_MARKER = "data-shell-drawer";

/**
 * Another modal dialog is open (every dialog in the app is a native modal
 * <dialog>). The ⌘K shortcut must not open the palette over it.
 */
export function isOtherDialogOpen(): boolean {
  return document.querySelector(`dialog[open]:not([${DRAWER_MARKER}])`) !== null;
}
