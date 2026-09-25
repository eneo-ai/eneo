/*
 * When an action removes the focused element (a row that left the list after
 * a delete or deactivate), keyboard users must not be left on <body>
 * (ACCESSIBILITY.md rule 2). Astryx has no hook for this: useFocusTrap only
 * restores focus when a trap it owns ends, and useListFocus moves focus
 * between items that exist. Dialogs return focus themselves
 * (src/components/ui/dialog-focus.ts, which shares isFocusLost); this is for
 * the page behind them.
 */

/** Focus is on nothing, inside a dialog that has closed, or on a closed menu's item. */
export function isFocusLost(): boolean {
  const active = document.activeElement;
  return (
    !active ||
    active === document.body ||
    active.closest('dialog:not([open]), [role="menu"]') !== null
  );
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
