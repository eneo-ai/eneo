"use client";

import { createContext, useContext, useEffect, useRef } from "react";

export type ShellContextValue = {
  /** Opens the ⌘K command palette. */
  openPalette: () => void;
  /** Opens the "Skapa yta" dialog (the create-space flow of /spaces/list). */
  openCreateSpace: () => void;
  /**
   * Call before navigating to `href` from a shell link. When it opens another
   * conversation on the page that is already showing (only the query
   * changes), the shell remounts the page once the URL arrives, so the chat
   * starts from the URL instead of keeping its current conversation.
   */
  prepareNavigation: (href: string) => void;
};

export const ShellContext = createContext<ShellContextValue | null>(null);

export function useShell(): ShellContextValue {
  const context = useContext(ShellContext);
  if (!context) throw new Error("useShell must be used inside the app shell");
  return context;
}

const NON_TEXT_INPUT_TYPES = new Set([
  "button",
  "checkbox",
  "color",
  "file",
  "image",
  "radio",
  "range",
  "reset",
  "submit"
]);

/** Focus is in something the user types into: the shortcut must not steal the keys. */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  if (target instanceof HTMLInputElement) return !NON_TEXT_INPUT_TYPES.has(target.type);
  return false;
}

/** ⌘K on macOS, Ctrl+K elsewhere (either is accepted), without other modifiers. */
export function isPaletteShortcut(event: KeyboardEvent): boolean {
  return (
    (event.metaKey || event.ctrlKey) &&
    !event.altKey &&
    !event.shiftKey &&
    event.key.toLowerCase() === "k"
  );
}

/**
 * Global ⌘K / Ctrl+K: toggles the command palette. While focus is in a text
 * field the shortcut is left alone (it would hijack typing and editors' own
 * Ctrl+K), except that it still closes an open palette.
 */
export function usePaletteShortcut(isOpen: boolean, toggle: () => void) {
  const state = useRef({ isOpen, toggle });
  useEffect(() => {
    state.current = { isOpen, toggle };
  });

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.isComposing || event.repeat) return;
      if (!isPaletteShortcut(event)) return;
      if (!state.current.isOpen && isEditableTarget(event.target)) return;
      event.preventDefault();
      state.current.toggle();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
