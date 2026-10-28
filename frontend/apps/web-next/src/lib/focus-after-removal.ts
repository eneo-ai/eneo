/**
 * Where keyboard focus goes when a row leaves its list by what its own control
 * did (a row's menu, after the row is deleted): taken before the change, it
 * names the first control of the row that took the removed row's place, else
 * of the row before it. Null while `anchor` is still in the page, or when no
 * neighbour is left.
 */
export function focusAfterRemoval(anchor: HTMLElement | null): () => HTMLElement | null {
  const row = anchor?.closest<HTMLElement>("tr, li") ?? null;
  const list = row?.parentElement ?? null;
  const index = row && list ? Array.prototype.indexOf.call(list.children, row) : -1;
  return () => {
    if (!anchor || anchor.isConnected || !list?.isConnected || index < 0) return null;
    const rows = Array.from(list.children);
    const neighbour = rows[index] ?? rows[index - 1];
    return neighbour?.querySelector<HTMLElement>("a[href], button:not(:disabled)") ?? null;
  };
}
