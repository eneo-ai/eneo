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

/** Marks the navigation drawer, the one modal the palette may open over. */
export const DRAWER_MARKER = "data-shell-drawer";

/**
 * Another modal dialog is open (every dialog in the app is a native modal
 * <dialog>). The ⌘K shortcut must not open the palette over it.
 */
export function isOtherDialogOpen(): boolean {
  return document.querySelector(`dialog[open]:not([${DRAWER_MARKER}])`) !== null;
}
