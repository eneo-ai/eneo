/** Where a run's own page is. */
export function runHref(spaceRouteId: string, flowId: string, runId: string): string {
  return `/spaces/${spaceRouteId}/flows/${flowId}/runs/${runId}`;
}
