/** UI state only: changing a step or tab must not reload the flow or remount its draft. */
export function parseFlowSearch(search: { step?: unknown; tab?: unknown }): {
  step?: string;
  tab?: "runs";
} {
  return {
    step: typeof search.step === "string" && search.step ? search.step : undefined,
    tab: search.tab === "runs" ? "runs" : undefined
  };
}

/**
 * A space's flow list keeps its search (?q=) in the address, so a reload, a
 * shared link or a turn of the phone keeps it; like a flow's step and tab, it
 * never reloads the list.
 */
export function parseFlowListSearch(search: { q?: unknown }): { q?: string } {
  return { q: typeof search.q === "string" && search.q.trim() ? search.q.trim() : undefined };
}

/** The list's address with its search changed; "" leaves it out. */
export function flowListHref(
  pathname: string,
  current: Pick<URLSearchParams, "toString">,
  change: { q?: string }
): string {
  const params = new URLSearchParams(current.toString());
  if (change.q) params.set("q", change.q);
  else params.delete("q");
  return params.size > 0 ? `${pathname}?${params}` : pathname;
}
