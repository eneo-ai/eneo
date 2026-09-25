"use client";

import * as React from "react";
import { isFocusLost } from "@/lib/focus-rescue";

/*
 * Focus return for dialogs (ACCESSIBILITY.md rule 2: when the focused element
 * disappears, move focus somewhere logical). Astryx Dialog returns focus to
 * the element that was focused when it opened; this module covers the cases
 * it cannot, for every dialog in the app.
 */

/**
 * The element focused last, kept after it leaves the page: a menu item that
 * opened a dialog is gone by the time the dialog opens. One listener for the
 * app, added when the first dialog mounts.
 */
let lastFocused: Element | null = null;
let isTrackingFocus = false;

export function trackFocus() {
  if (isTrackingFocus) return;
  isTrackingFocus = true;
  document.addEventListener(
    "focusin",
    (event) => {
      lastFocused = event.target instanceof Element ? event.target : null;
    },
    true
  );
}

/** The button that opens `menu` (Astryx: aria-controls; Radix: aria-labelledby). */
function menuTrigger(menu: Element): HTMLElement | null {
  const byControls = menu.id
    ? document.querySelector<HTMLElement>(
        `[aria-haspopup="menu"][aria-controls="${CSS.escape(menu.id)}"]`
      )
    : null;
  if (byControls) return byControls;
  const labelledBy = menu.getAttribute("aria-labelledby");
  const byLabel = labelledBy ? document.getElementById(labelledBy) : null;
  return byLabel?.getAttribute("aria-haspopup") === "menu" ? byLabel : null;
}

/**
 * Where focus goes back when the dialog closes: the element that had focus
 * when it opened or, when that was an item of a menu (gone once the dialog is
 * up), the button that opened the menu.
 */
export function returnTarget(): HTMLElement | null {
  const active = document.activeElement;
  const opener =
    active && active !== document.body
      ? active
      : lastFocused && !lastFocused.isConnected
        ? lastFocused
        : null;
  if (!(opener instanceof HTMLElement)) return null;
  const menu = opener.closest('[role="menu"]');
  if (menu) return menuTrigger(menu);
  return opener.isConnected ? opener : null;
}

/**
 * Astryx Dialog returns focus to the element focused when it opened. This
 * covers what it cannot: that element is gone (a menu item), the browser never
 * focused the trigger on click (Safari), or the dialog unmounted while open.
 * It only acts when focus was actually lost.
 */
export function useReturnFocus(open: boolean, triggerRef: React.RefObject<HTMLElement | null>) {
  const targetRef = React.useRef<HTMLElement | null>(null);
  const openRef = React.useRef(open);

  React.useEffect(trackFocus, []);

  // Layout effect: runs before Astryx's showModal() moves focus into the dialog.
  React.useLayoutEffect(() => {
    openRef.current = open;
    if (open) targetRef.current = returnTarget() ?? triggerRef.current;
  }, [open, triggerRef]);

  // Passive effect: runs after Astryx Dialog (a child) has closed and refocused.
  React.useEffect(() => {
    const target = targetRef.current;
    if (open || !target) return;
    targetRef.current = null;
    if (isFocusLost() && target.isConnected) target.focus();
  }, [open]);

  React.useEffect(
    () => () => {
      const target = targetRef.current;
      if (openRef.current && target?.isConnected && isFocusLost()) target.focus();
    },
    []
  );
}
