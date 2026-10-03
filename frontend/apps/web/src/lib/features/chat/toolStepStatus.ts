export type ToolStepStatus = "preparing" | "running" | "complete" | "failed" | "denied";

/** New calls require a terminal result; legacy history may lack a status. */
export function toolStepStatus(
  status: string | null | undefined,
  denied: boolean,
  streaming: boolean,
  legacyRunning = false
): ToolStepStatus {
  if (denied || status === "denied" || status === "timeout_denied") return "denied";
  if (status === "failed") return "failed";
  if (status === "pending" || status === "approved" || status === "deferred") {
    if (!streaming) return "failed";
    return status === "approved" ? "running" : "preparing";
  }
  if (status === "succeeded" || status === "completed") return "complete";
  return legacyRunning ? "running" : "complete";
}

/**
 * Presentation only: a failed call followed by an explicit success from the same
 * tool is an earlier attempt, not a failure of the whole turn. Arguments can
 * change on retry (e.g. splitting an oversized chart into two charts).
 * This does not claim the original call succeeded or that every requested
 * operation was fulfilled. Keep its actual status and result for diagnostics.
 */
export function previousToolAttemptIndexes(
  calls: readonly {
    server_name: string;
    tool_name: string;
    result_status?: string | null;
    approved?: boolean;
  }[]
): Set<number> {
  const successfulTools = new Set<string>();
  const previousAttempts = new Set<number>();
  for (let i = calls.length - 1; i >= 0; i--) {
    const call = calls[i];
    if (call.approved === false) continue;
    const key = JSON.stringify([call.server_name, call.tool_name]);
    if (call.result_status === "succeeded" || call.result_status === "completed") {
      successfulTools.add(key);
    } else if (call.result_status === "failed" && successfulTools.has(key)) {
      previousAttempts.add(i);
    }
  }
  return previousAttempts;
}
