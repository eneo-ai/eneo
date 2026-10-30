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
