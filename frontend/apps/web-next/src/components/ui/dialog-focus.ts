import * as React from "react";
import { isFocusLost, notifyFocusLost } from "@/lib/focus-rescue";

/*
 * Focus return for dialogs (ACCESSIBILITY.md rule 2: when the focused element
 * disappears, move focus somewhere logical). Astryx Dialog returns focus to
 * the element that was focused when it opened; this module covers the cases
 * it cannot, for every dialog in the app. When the opener is gone too (the
 * dialog confirmed deleting its own row), the page behind the dialog is told
 * at that moment (`notifyFocusLost`) and rescues focus itself
 * (src/lib/focus-rescue.ts).
 */

/**
 * The element focused last, kept after it leaves the page: a menu item that
 * opened a dialog is gone by the time the dialog opens.
 */
let lastFocused: Element | null = null;
/**
 * The control pressed since focus last moved (or a key was pressed). Safari
 * (macOS and iOS) does not focus a button or link on click or tap, so the
 * button that opened a dialog never had focus and focus sits on <body>.
 */
let lastPressed: Element | null = null;
let isTrackingFocus = false;

const PRESSABLE = 'button, a[href], [role="button"], [role^="menuitem"]';

/** One set of listeners for the app, added when the first dialog mounts. */
export function trackFocus() {
  if (isTrackingFocus) return;
  isTrackingFocus = true;
  document.addEventListener(
    "focusin",
    (event) => {
      lastFocused = event.target instanceof Element ? event.target : null;
      lastPressed = null;
    },
    true
  );
  document.addEventListener(
    "pointerdown",
    (event) => {
      lastPressed = event.target instanceof Element ? event.target.closest(PRESSABLE) : null;
    },
    true
  );
  document.addEventListener(
    "keydown",
    () => {
      lastPressed = null;
    },
    true
  );
}

/** The button that opens `menu` (an Astryx menu button names it in aria-controls). */
function menuTrigger(menu: Element): HTMLElement | null {
  return menu.id
    ? document.querySelector<HTMLElement>(
        `[aria-haspopup="menu"][aria-controls="${CSS.escape(menu.id)}"]`
      )
    : null;
}

/** What opened the dialog: the focused element, else what focus or a press left behind. */
function findOpener(): Element | null {
  const active = document.activeElement;
  if (active && active !== document.body) return active;
  // Focus is on <body>: the opener was a menu item that is gone by now, or a
  // control the browser never focused when it was pressed (Safari).
  return lastPressed ?? (lastFocused && !lastFocused.isConnected ? lastFocused : null);
}

/**
 * Where focus goes back when the dialog closes: the element that opened it
 * or, when that was an item of a menu (gone once the dialog is up), the
 * button that opened the menu.
 */
export function returnTarget(): HTMLElement | null {
  const opener = findOpener();
  if (!(opener instanceof HTMLElement)) return null;
  const menu = opener.closest('[role="menu"]');
  if (menu) return menuTrigger(menu);
  return opener.isConnected ? opener : null;
}

/**
 * Astryx Dialog returns focus to the element focused when it opened. This
 * covers what it cannot: that element is gone (a menu item), the browser never
 * focused the trigger on click (Safari), or the dialog unmounted while open.
 * It only acts when focus was actually lost, and reports when it stays lost.
 */
export function useReturnFocus(open: boolean, triggerRef: React.RefObject<HTMLElement | null>) {
  const targetRef = React.useRef<HTMLElement | null>(null);
  const openRef = React.useRef(open);

  React.useEffect(trackFocus, []);

  // Layout effect: runs before Astryx's showModal() moves focus into the dialog.
  // Once per opening: StrictMode runs it again after the dialog's title took
  // focus, and a dialog that mounts open (a key per opening) would then
  // return focus to its own hidden title.
  React.useLayoutEffect(() => {
    openRef.current = open;
    if (open) targetRef.current ??= returnTarget() ?? triggerRef.current;
  }, [open, triggerRef]);

  // Passive effect: runs after Astryx Dialog (a child) has closed and refocused.
  React.useEffect(() => {
    const target = targetRef.current;
    if (open || !target) return;
    targetRef.current = null;
    returnFocusTo(target);
  }, [open]);

  // Unmounted while open: focus goes back once, from whichever comes first. A
  // close in an event (a click) has its passive cleanups flushed with the
  // commit. A close outside one (a request that answered) runs them later, after
  // a page's focus rescue has heard of the removal; the microtask queued in the
  // layout cleanup, before the dialog's nodes go, runs first: once the commit is
  // done, after the dialog's own return. The rescue then finds focus on the
  // opener and waits for that to go too (a deleted row's menu), as when the
  // dialog closes while kept. Remounted at once (StrictMode), the queued return
  // does nothing.
  const mountedRef = React.useRef(false);
  function returnAfterUnmount() {
    if (mountedRef.current || !openRef.current) return;
    openRef.current = false;
    returnFocusTo(targetRef.current);
  }
  React.useLayoutEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      queueMicrotask(returnAfterUnmount);
    };
  }, []);
  React.useEffect(() => () => returnAfterUnmount(), []);
}

/** Places focus on `target` when it is lost; when it stays lost, the page is told. */
function returnFocusTo(target: HTMLElement | null) {
  if (!isFocusLost()) return;
  if (target?.isConnected) target.focus();
  if (isFocusLost()) notifyFocusLost();
  // An opener the layout now hides (the screen became a phone's) takes no focus: the page does.
  if (isFocusLost() && target?.isConnected && target.getClientRects().length === 0) {
    document.getElementById("main-content")?.focus();
  }
}
