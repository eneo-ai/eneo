import { queryOptions } from "@tanstack/react-query";
import { isTerminal } from "./run-status";
import { deliverySignature, deliveryUnderWay } from "./run-webhooks";
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
 * Once the run has finished, its steps no longer change (a retry is a new run), and the graph the
 * last pair holds was read after the run had finished. Only whether speakers are identified can
 * still change in it, as it follows the installation's set-up. The graph is kept, and the status
 * read alone, once the last pair's run had finished and:
 * - its result was on its way;
 * - the new status shows the result moved on since the last pair, so the move is shown even when
 *   the graph could not be read now; or
 * - its result was given up and the last answer was younger than the client's `staleTime` when
 *   the read began: a fresh remount, made to see whether it was sent again.
 * Otherwise the graph is read again after the status, as on an ordinary stale return to a
 * finished run.
 *
 * Callers add their own polling (`refetchInterval`) and mount rule.
 */
export function runProgressQueryOptions(flowId: string, runId: string) {
  return queryOptions({
    queryKey: runKeys.progress(flowId, runId),
    queryFn: async ({ client, queryKey, signal }): Promise<RunProgress> => {
      // The last answer, and whether it was fresh, as the read begins: not after the status answers.
      const last = client.getQueryState<RunProgress>(queryKey);
      const staleTime = client.getDefaultOptions().queries?.staleTime;
      const fresh =
        last !== undefined &&
        typeof staleTime === "number" &&
        Date.now() - last.dataUpdatedAt < staleTime;
      const status = await getRunStatus(flowId, runId, signal);
      const kept =
        last?.data && keepsGraph(last.data.status, status, fresh) ? last.data.graph : null;
      return { status, graph: kept ?? (await getRunGraph(flowId, runId, signal)) };
    }
  });
}

/** Whether the last pair's graph stands beside `next` (see `runProgressQueryOptions`). */
function keepsGraph(last: RunSummary, next: RunSummary, fresh: boolean): boolean {
  if (!isTerminal(last.status)) return false;
  const delivery = last.result_delivery;
  // ponytail: the last answer's age stands for the graph's; remounts faster than `staleTime` on a
  // given-up result, and a result that moved on, put the graph's read off until a stale read finds
  // the result settled and unchanged.
  return (
    deliveryUnderWay(delivery) ||
    deliverySignature(next.result_delivery) !== deliverySignature(delivery) ||
    (delivery?.state === "dead_lettered" && fresh)
  );
}
