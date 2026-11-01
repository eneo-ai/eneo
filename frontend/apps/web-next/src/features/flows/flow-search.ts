import type { FlowListStatus } from "./flow-list-filter";

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
 * A space's flow list keeps its search (?q=) and state filter (?status=) in
 * the address, so a reload, a shared link or a turn of the phone keeps them;
 * like a flow's step and tab, they never reload the list.
 */
export function parseFlowListSearch(search: { q?: unknown; status?: unknown }): {
  q?: string;
  status?: Exclude<FlowListStatus, "all">;
} {
  return {
    q: typeof search.q === "string" && search.q.trim() ? search.q.trim() : undefined,
    status: search.status === "published" || search.status === "drafts" ? search.status : undefined
  };
}

/** The list's address with the given parts of its state changed; "all" and "" leave theirs out. */
export function flowListHref(
  pathname: string,
  current: Pick<URLSearchParams, "toString">,
  change: { q?: string; status?: FlowListStatus }
): string {
  const params = new URLSearchParams(current.toString());
  for (const [key, value] of Object.entries(change)) {
    if (value && value !== "all") params.set(key, value);
    else params.delete(key);
  }
  return params.size > 0 ? `${pathname}?${params}` : pathname;
}
