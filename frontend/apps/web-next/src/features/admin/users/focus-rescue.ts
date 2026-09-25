/**
 * Moves focus to `target` when an action removed the focused element (a row
 * that left the list after deactivate/delete), so keyboard users are not left
 * on <body> (ACCESSIBILITY.md rule 2). Checks after the list re-rendered and
 * again after a closing dialog has handed focus back; it only acts when focus
 * was actually lost.
 */
export function rescueFocus(target: HTMLElement | null) {
  const check = () => {
    const active = document.activeElement;
    if (!active || active === document.body) target?.focus();
  };
  requestAnimationFrame(check);
  window.setTimeout(check, 500);
}
