/*
 * When an action removes the focused element (a row that left the list after
 * a delete or deactivate), keyboard users must not be left on <body>
 * (ACCESSIBILITY.md rule 2). Astryx has no hook for this: useFocusTrap only
 * restores focus when a trap it owns ends, and useListFocus moves focus
 * between items that exist. Dialogs return focus themselves
 * (src/components/ui/dialog-focus.ts, which shares isFocusLost); this is for
 * the page behind them.
 */

/**
 * A menu that is still in the page but not shown: a closed Astryx menu (a
 * hidden popover) or a Radix menu playing its close animation. Focus left on
 * one of its items is on nothing the user can see.
 */
function isHiddenMenu(menu: Element): boolean {
  if (menu.closest('[hidden], [data-state="closed"]')) return true;
  const popover = menu.closest("[popover]");
  // Without the Popover API (jsdom) a popover's state cannot be read.
  if (!popover || typeof HTMLElement.prototype.showPopover !== "function") return false;
  return !popover.matches(":popover-open");
}

/**
 * Focus is on nothing, inside a dialog that has closed, or on an item of a
 * menu that is no longer shown. An open menu (one the user just opened) is
 * not lost focus.
 */
export function isFocusLost(): boolean {
  const active = document.activeElement;
  if (!active || active === document.body) return true;
  if (active.closest("dialog:not([open])")) return true;
  const menu = active.closest('[role="menu"]');
  return menu !== null && isHiddenMenu(menu);
}

/**
 * Moves focus to `target` (a list heading or panel with tabIndex -1) once the
 * list re-rendered, and again after a closing dialog has handed focus back;
 * it only acts when focus was actually lost.
 */
export function rescueFocus(target: HTMLElement | null) {
  const check = () => {
    if (isFocusLost()) target?.focus();
  };
  requestAnimationFrame(check);
  window.setTimeout(check, 500);
}
