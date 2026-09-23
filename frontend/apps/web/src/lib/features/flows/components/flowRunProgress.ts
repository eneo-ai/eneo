import { getLocale } from "$lib/paraglide/runtime";
import type {
  FlowGraph,
  FlowGraphNode,
  FlowRunOutputPayload,
  FlowRunResultFile,
  FlowRunStep
} from "@eneo/eneo-js";

export type FlowRunProgressStep = {
  stepOrder: number;
  label: string;
  status: string;
  inputSource?: string;
  outputMode?: string;
  outputType?: string;
  /** Audio step whose transcription also labels speakers (external service). */
  speakerIdentification?: boolean;
  errorMessage?: string | null;
  errorCode?: string | null;
  numTokensInput?: number | null;
  numTokensOutput?: number | null;
  inputPayload?: Record<string, unknown> | null;
  outputPayload?: FlowRunOutputPayload | null;
  resultFiles: FlowRunResultFile[];
  startedAt?: string | null;
  finishedAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  /** The status moved on since the step's outputs were read (audited read on
   *  demand); outputs, files and end time are withheld until re-read. */
  detailsStale?: boolean;
};

export type FlowRunProgressSnapshot = {
  steps: FlowRunProgressStep[];
};

export type FlowRunProgressStats = {
  total: number;
  completed: number;
  failed: number;
  running: number;
  pending: number;
  terminal: number;
  progressRatio: number;
};

export function buildFlowRunProgressSnapshot(
  graph: FlowGraph | null,
  steps: FlowRunStep[],
  options: {
    /** The graph was read AFTER the step list (a status poll): its statuses
     *  win and a step it moved past has stale details. Without it, graph and
     *  steps come from one read and the audited step list is the authority. */
    statusOverlay?: boolean;
  } = {}
): FlowRunProgressSnapshot {
  const statusOverlay = options.statusOverlay === true;
  const stepsByOrder = new Map(steps.map((step) => [step.step_order, step] as const));
  const graphNodes = (graph?.nodes ?? [])
    .filter(
      (node): node is FlowGraphNode & { step_order: number } => typeof node.step_order === "number"
    )
    .sort((a, b) => a.step_order - b.step_order);

  const knownOrders = new Set<number>();
  const viewSteps: FlowRunProgressStep[] = [];

  for (const node of graphNodes) {
    knownOrders.add(node.step_order);
    const live = stepsByOrder.get(node.step_order);
    // On a status overlay the graph is the fresher status, and when it has
    // moved past the step list's status the list's content for that step
    // describes an earlier state.
    const detailsStale =
      statusOverlay &&
      live !== undefined &&
      node.run_status != null &&
      live.status !== node.run_status;
    viewSteps.push({
      stepOrder: node.step_order,
      label: node.label || `Step ${node.step_order}`,
      status: statusOverlay
        ? (node.run_status ?? live?.status ?? "pending")
        : (live?.status ?? node.run_status ?? "pending"),
      inputSource: typeof node.input_source === "string" ? node.input_source : undefined,
      outputMode: typeof node.output_mode === "string" ? node.output_mode : undefined,
      outputType: typeof node.output_type === "string" ? node.output_type : undefined,
      speakerIdentification: node.speaker_identification === true ? true : undefined,
      errorMessage: detailsStale
        ? (node.error_message ?? null)
        : (live?.error_message ?? node.error_message ?? null),
      errorCode: detailsStale ? null : (live?.error_code ?? null),
      numTokensInput: statusOverlay
        ? (node.num_tokens_input ?? live?.num_tokens_input ?? null)
        : (live?.num_tokens_input ?? node.num_tokens_input ?? null),
      numTokensOutput: statusOverlay
        ? (node.num_tokens_output ?? live?.num_tokens_output ?? null)
        : (live?.num_tokens_output ?? node.num_tokens_output ?? null),
      inputPayload: live?.input_payload_json ?? null,
      outputPayload: detailsStale ? null : (live?.output_payload_json ?? null),
      resultFiles: detailsStale ? [] : (live?.result_files ?? []),
      startedAt: live?.started_at ?? null,
      finishedAt: detailsStale ? null : (live?.finished_at ?? null),
      createdAt: live?.created_at ?? null,
      updatedAt: detailsStale ? null : (live?.updated_at ?? null),
      ...(detailsStale ? { detailsStale: true } : {})
    });
  }

  for (const live of [...steps].sort((a, b) => a.step_order - b.step_order)) {
    if (knownOrders.has(live.step_order)) continue;
    viewSteps.push({
      stepOrder: live.step_order,
      label: `Step ${live.step_order}`,
      status: live.status,
      errorMessage: live.error_message ?? null,
      errorCode: live.error_code ?? null,
      numTokensInput: live.num_tokens_input ?? null,
      numTokensOutput: live.num_tokens_output ?? null,
      inputPayload: live.input_payload_json ?? null,
      outputPayload: live.output_payload_json ?? null,
      resultFiles: live.result_files ?? [],
      startedAt: live?.started_at ?? null,
      finishedAt: live?.finished_at ?? null,
      createdAt: live.created_at ?? null,
      updatedAt: live.updated_at ?? null
    });
  }

  return { steps: viewSteps.sort((a, b) => a.stepOrder - b.stepOrder) };
}

export function getFlowRunProgressStats(snapshot: FlowRunProgressSnapshot): FlowRunProgressStats {
  const total = snapshot.steps.length;
  let completed = 0;
  let failed = 0;
  let running = 0;
  let pending = 0;

  for (const step of snapshot.steps) {
    if (step.status === "completed") completed += 1;
    else if (step.status === "failed" || step.status === "cancelled") failed += 1;
    else if (step.status === "running") running += 1;
    else pending += 1;
  }

  const terminal = completed + failed;
  const progressRatio = total === 0 ? 0 : terminal / total;
  return { total, completed, failed, running, pending, terminal, progressRatio };
}

export function getFlowRunFocusedStepOrder(snapshot: FlowRunProgressSnapshot): number | null {
  const runningStep = snapshot.steps.find((step) => step.status === "running");
  if (runningStep) return runningStep.stepOrder;

  const failedStep = snapshot.steps.find(
    (step) => step.status === "failed" || step.status === "cancelled"
  );
  if (failedStep) return failedStep.stepOrder;

  const nextPendingStep = snapshot.steps.find(
    (step) => step.status === "queued" || step.status === "pending"
  );
  if (nextPendingStep) return nextPendingStep.stepOrder;

  return snapshot.steps.at(-1)?.stepOrder ?? null;
}

export function formatFlowRunStepDuration(step: FlowRunProgressStep): string | null {
  if (step.status !== "completed" && step.status !== "failed" && step.status !== "cancelled") {
    return null;
  }
  const start = step.startedAt ?? step.createdAt;
  const end = step.finishedAt ?? step.updatedAt;
  if (!start || !end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return formatFlowRunDuration(ms);
}

/**
 * A duration in the reader's language with its two largest units, each
 * rounded to the smaller one first: "4 min 59 s", "1 tim 5 min", "2 d 3 tim".
 * One owner for the history table, the evidence view and the progress view.
 */
export function formatFlowRunDuration(ms: number, locale: string = getLocale()): string {
  const unit = (name: string, value: number) =>
    new Intl.NumberFormat(locale, { style: "unit", unit: name, unitDisplay: "short" }).format(
      value
    );
  const pair = (big: string, bigValue: number, small: string, smallValue: number) =>
    smallValue === 0 ? unit(big, bigValue) : `${unit(big, bigValue)} ${unit(small, smallValue)}`;
  const value = Math.max(0, ms);
  if (value < 1000) return unit("millisecond", Math.round(value));
  const seconds = Math.round(value / 1000);
  if (seconds < 60) return unit("second", seconds);
  if (seconds < 3600) return pair("minute", Math.floor(seconds / 60), "second", seconds % 60);
  const minutes = Math.round(value / 60_000);
  if (minutes < 1440) return pair("hour", Math.floor(minutes / 60), "minute", minutes % 60);
  const hours = Math.round(value / 3_600_000);
  return pair("day", Math.floor(hours / 24), "hour", hours % 24);
}

export function formatFlowRunElapsed(startedAtIso: string | null, nowMs: number): string | null {
  if (!startedAtIso) return null;
  const started = new Date(startedAtIso).getTime();
  if (!Number.isFinite(started)) return null;
  const delta = Math.max(0, nowMs - started);
  return formatFlowRunDuration(delta);
}
