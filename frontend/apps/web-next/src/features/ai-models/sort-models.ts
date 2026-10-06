type SortableModel = {
  org?: string | null;
  nickname?: string | null;
};

/**
 * Stable model ordering: grouped by vendor (`org`), then by `nickname`.
 * Returns a new array (unlike the Svelte original, which sorted in place).
 */
export function sortModels<T extends SortableModel>(models: readonly T[]): T[] {
  return [...models].sort((a, b) => {
    if ((a.org ?? "") === (b.org ?? "")) {
      return (a.nickname ?? "a") > (b.nickname ?? "b") ? 1 : -1;
    }
    return (a.org ?? "a") > (b.org ?? "b") ? 1 : -1;
  });
}
