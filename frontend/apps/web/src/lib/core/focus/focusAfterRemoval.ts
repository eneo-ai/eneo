/**
 * Keeps keyboard focus near a control that goes away by what it does: a row's menu
 * after the row is deleted, where a closing dialog would hand focus back to a
 * trigger that is gone and focus would fall to the body.
 *
 * Create it before the change; call `settle()` when focus would return (a dialog's
 * close auto-focus). The neighbouring row's first control takes focus, else the
 * `[data-content-heading]` of the surrounding `[data-focus-region]`.
 */
export function focusAfterRemoval(anchor: HTMLElement | null) {
  const row = anchor?.closest<HTMLElement>("tr, li") ?? null;
  const list = row?.parentElement ?? null;
  const index = row && list ? Array.prototype.indexOf.call(list.children, row) : -1;
  const region = anchor?.closest<HTMLElement>("[data-focus-region]") ?? null;
  return {
    /** Moves focus and returns true when the anchor is gone; false leaves focus alone. */
    settle(): boolean {
      if (!anchor || anchor.isConnected) return false;
      const rows = list?.isConnected ? Array.from(list.children) : [];
      const neighbour = rows[index] ?? rows[index - 1];
      const target =
        neighbour?.querySelector<HTMLElement>("a[href], button:not(:disabled)") ??
        (region?.isConnected ? region.querySelector<HTMLElement>("[data-content-heading]") : null);
      if (!target) return false;
      target.focus();
      return true;
    }
  };
}
