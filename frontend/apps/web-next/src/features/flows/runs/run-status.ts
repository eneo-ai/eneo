import { FLOW_RUN_STATUS_CAPABILITIES } from "@eneo/eneo-js/flows/run-status-capabilities";
import type { StatusTone } from "@/components/composites/status-label";
import type { RunStatus, RunStepStatus, RunSummary } from "./runs-api";

/**
 * What a run's status means for the screens, from the backend's own status
 * table (generated from the core's enum into eneo-js): whether to keep
 * polling, whether cancel or redispatch is a valid action, whether a review
 * is open. A status the table does not know is treated as settled, so the
 * client never polls or offers actions on a guess.
 */

const CAPABILITIES = new Map(
  FLOW_RUN_STATUS_CAPABILITIES.map((capability) => [capability.status as string, capability])
);

export function shouldPoll(status: string): boolean {
  return CAPABILITIES.get(status)?.should_poll ?? false;
}

export function isCancellable(status: string): boolean {
  return CAPABILITIES.get(status)?.is_cancellable ?? false;
}

export function isTerminal(status: string): boolean {
  return CAPABILITIES.get(status)?.is_terminal ?? false;
}

export function isAwaitingReview(status: string): boolean {
  return CAPABILITIES.get(status)?.is_awaiting_review ?? false;
}

/**
 * Whether to offer "send again" for a queued run: the status allows it and
 * the server's dispatch clock says it is due, or its bounded dispatch gave
 * up. A queued run whose clock has not come due would get `0` back.
 */
export function canRedispatch(
  run: Pick<RunSummary, "status" | "dispatch_next_attempt_at" | "dispatch_exhausted_at">,
  now: number
): boolean {
  if (!(CAPABILITIES.get(run.status)?.can_request_redispatch ?? false)) return false;
  if (run.dispatch_exhausted_at) return true;
  if (!run.dispatch_next_attempt_at) return false;
  const due = Date.parse(run.dispatch_next_attempt_at);
  return Number.isFinite(due) && due <= now;
}

type StatusView = { tone: StatusTone; labelKey: string; isPulsing: boolean };

const RUN_STATUS_VIEWS: Record<RunStatus, StatusView> = {
  queued: { tone: "neutral", labelKey: "flow_runs_status_queued", isPulsing: false },
  running: { tone: "accent", labelKey: "flow_runs_status_running", isPulsing: true },
  awaiting_review: {
    tone: "warning",
    labelKey: "flow_runs_status_awaiting_review",
    isPulsing: false
  },
  completed: { tone: "success", labelKey: "flow_runs_status_completed", isPulsing: false },
  failed: { tone: "error", labelKey: "flow_runs_status_failed", isPulsing: false },
  cancelled: { tone: "neutral", labelKey: "flow_runs_status_cancelled", isPulsing: false }
};

const STEP_STATUS_VIEWS: Record<RunStepStatus, StatusView> = {
  pending: { tone: "neutral", labelKey: "flow_runs_step_status_pending", isPulsing: false },
  running: { tone: "accent", labelKey: "flow_runs_step_status_running", isPulsing: true },
  completed: { tone: "success", labelKey: "flow_runs_step_status_completed", isPulsing: false },
  failed: { tone: "error", labelKey: "flow_runs_step_status_failed", isPulsing: false },
  cancelled: { tone: "neutral", labelKey: "flow_runs_step_status_cancelled", isPulsing: false }
};

const UNKNOWN_VIEW: StatusView = {
  tone: "neutral",
  labelKey: "flow_runs_status_unknown",
  isPulsing: false
};

/** How a step of an ended run that never ran shows (`stepNeverRan`). */
export const NOT_RUN_STEP_VIEW: StatusView = {
  tone: "neutral",
  labelKey: "flow_run_more_step_not_run",
  isPulsing: false
};

/** How a run's status shows: its text (which carries the meaning) and the dot's tone. */
export function runStatusView(status: string): StatusView {
  return RUN_STATUS_VIEWS[status as RunStatus] ?? UNKNOWN_VIEW;
}

/** How a step's status in a run shows. */
export function stepStatusView(status: string | null | undefined): StatusView {
  return (status && STEP_STATUS_VIEWS[status as RunStepStatus]) || UNKNOWN_VIEW;
}

/**
 * The polling cadence the run API asks for: about every 2 seconds for the
 * first 30 seconds, then every 5, then every 15. The clock starts at the
 * last change this client saw, so a run that just moved is followed closely
 * and one that waits for review costs little.
 */
export function pollDelayMs(msSinceChange: number): number {
  if (msSinceChange < 30_000) return 2_000;
  if (msSinceChange < 5 * 60_000) return 5_000;
  return 15_000;
}

/** The list keeps polling only while one of its runs is still moving or waits for review. */
export function listNeedsPolling(runs: readonly Pick<RunSummary, "status">[]): boolean {
  return runs.some((run) => shouldPoll(run.status));
}

/** What changes when a run in the list moves on; equal signatures mean nothing new. */
export function listSignature(
  runs: readonly Pick<RunSummary, "id" | "status" | "revision">[]
): string {
  return runs.map((run) => `${run.id}:${run.status}:${run.revision}`).join("|");
}

/** How long a run took, or null while it has not finished. */
export function runDurationMs(
  run: Pick<RunSummary, "created_at" | "started_at" | "finished_at">
): number | null {
  if (!run.finished_at) return null;
  const start = Date.parse(run.started_at ?? run.created_at);
  const end = Date.parse(run.finished_at);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  return end - start;
}

/**
 * How long a run that is still going (queued, running or waiting for
 * review) has gone on at `now`, from its start or, while it has not
 * started, its creation; null once it has ended. With several going at
 * once, how long each has waited is what the list's reader is after.
 */
export function runElapsedMs(
  run: Pick<RunSummary, "status" | "created_at" | "started_at" | "finished_at">,
  now: number
): number | null {
  if (run.finished_at || !shouldPoll(run.status)) return null;
  const start = Date.parse(run.started_at ?? run.created_at);
  return Number.isFinite(start) && now >= start ? now - start : null;
}

/**
 * The runs whose status moved since the list was last seen, in list order,
 * so their new state can be announced. A run the list did not show before
 * (a new run, a newly loaded page) is not a change.
 */
export function statusChanges<T extends Pick<RunSummary, "id" | "status">>(
  previous: ReadonlyMap<string, string>,
  runs: readonly T[]
): T[] {
  return runs.filter((run) => {
    const before = previous.get(run.id);
    return before !== undefined && before !== run.status;
  });
}

/**
 * Follows a list or a run while it moves: each answer that differs from the
 * last restarts the clock, and the next delay is `pollDelayMs` of the time
 * since then. `false` once nothing needs polling.
 */
export function createPollClock(now: () => number = Date.now) {
  let signature: string | null = null;
  let changedAt = now();
  return (nextSignature: string, active: boolean): number | false => {
    if (nextSignature !== signature) {
      signature = nextSignature;
      changedAt = now();
    }
    return active ? pollDelayMs(now() - changedAt) : false;
  };
}
