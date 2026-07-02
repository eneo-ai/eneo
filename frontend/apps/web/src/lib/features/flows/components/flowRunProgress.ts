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
  steps: FlowRunStep[]
): FlowRunProgressSnapshot {
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
    viewSteps.push({
      stepOrder: node.step_order,
      label: node.label || `Step ${node.step_order}`,
      status: live?.status ?? node.run_status ?? "pending",
      inputSource: typeof node.input_source === "string" ? node.input_source : undefined,
      outputMode: typeof node.output_mode === "string" ? node.output_mode : undefined,
      outputType: typeof node.output_type === "string" ? node.output_type : undefined,
      errorMessage: live?.error_message ?? node.error_message ?? null,
      errorCode: live?.error_code ?? null,
      numTokensInput: live?.num_tokens_input ?? node.num_tokens_input ?? null,
      numTokensOutput: live?.num_tokens_output ?? node.num_tokens_output ?? null,
      inputPayload: live?.input_payload_json ?? null,
      outputPayload: live?.output_payload_json ?? null,
      resultFiles: live?.result_files ?? [],
      startedAt: live?.started_at ?? null,
      finishedAt: live?.finished_at ?? null,
      createdAt: live?.created_at ?? null,
      updatedAt: live?.updated_at ?? null
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

export function formatFlowRunDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  if (seconds === 0) return `${minutes}m`;
  return `${minutes}m ${seconds}s`;
}

export function formatFlowRunElapsed(startedAtIso: string | null, nowMs: number): string | null {
  if (!startedAtIso) return null;
  const started = new Date(startedAtIso).getTime();
  if (!Number.isFinite(started)) return null;
  const delta = Math.max(0, nowMs - started);
  return formatFlowRunDuration(delta);
}
