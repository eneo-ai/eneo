export function shouldHandleFlowRunsReload(
  reloadTrigger: number,
  lastHandledReloadTrigger: number
): boolean {
  return reloadTrigger > lastHandledReloadTrigger;
}
