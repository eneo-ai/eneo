import { queryOptions } from "@tanstack/react-query";
import { isTerminal } from "./run-status";
import { deliveryUnderWay } from "./run-webhooks";
import { getRunGraph, getRunStatus, runKeys, type RunGraph, type RunSummary } from "./runs-api";

/** A run's content-free status and the graph of its steps, read as one pair. */
export type RunProgress = { status: RunSummary; graph: RunGraph };

/**
 * Whether the run has finished and its result, sent after it, is on its way or was given up: what
 * still moves is its status, and a given-up result can be sent again from elsewhere.
 */
export function followsResultOnly(
  status: Pick<RunSummary, "status" | "result_delivery"> | undefined
): boolean {
  if (!status || !isTerminal(status.status)) return false;
  const delivery = status.result_delivery;
  return deliveryUnderWay(delivery) || delivery?.state === "dead_lettered";
}

/**
 * A run's progress as the run page and the chat's run card follow it, the one read of its
 * `/status/` on these screens: one cache entry, written only by its own fetches, which TanStack
 * runs one at a time (a fetch asked for while one runs joins it or cancels it, and a cancelled
 * fetch's answer is dropped), so an older answer never replaces a newer one.
 *
 * Each fetch reads the status first and the graph after it, and publishes them as one pair: never
 * a new status beside an older graph, nor a finished run beside a last step still running (the
 * step and the run complete in one commit). It costs one status round trip on each read of both.
 *
 * Once the run has finished, its graph no longer changes (a retry is a new run), and the graph the
 * last pair holds was read after the run had finished. It is kept, and the status read alone,
 * while the run's result is on its way, and when it was given up and the last answer is younger
 * than the client's `staleTime`: a fresh remount, made to see whether it was sent again. An
 * ordinary stale return reads the graph again, as for any finished run: it says whether speakers
 * are identified, which follows the installation's set-up.
 *
 * Callers add their own polling (`refetchInterval`) and mount rule.
 */
export function runProgressQueryOptions(flowId: string, runId: string) {
  return queryOptions({
    queryKey: runKeys.progress(flowId, runId),
    queryFn: async ({ client, queryKey, signal }): Promise<RunProgress> => {
      const status = await getRunStatus(flowId, runId, signal);
      const last = client.getQueryState<RunProgress>(queryKey);
      const kept =
        last?.data &&
        keepsGraph(
          last.data.status,
          last.dataUpdatedAt,
          client.getDefaultOptions().queries?.staleTime
        )
          ? last.data.graph
          : null;
      return { status, graph: kept ?? (await getRunGraph(flowId, runId, signal)) };
    }
  });
}

/** Whether the last pair's graph stands for the next read (see `runProgressQueryOptions`). */
function keepsGraph(last: RunSummary, readAt: number, staleTime: unknown): boolean {
  if (!followsResultOnly(last)) return false;
  // ponytail: the last answer's age stands for the graph's; remounts faster than `staleTime` on a
  // given-up result put the graph's read off until a stale return.
  return (
    deliveryUnderWay(last.result_delivery) ||
    (typeof staleTime === "number" && Date.now() - readAt < staleTime)
  );
}
