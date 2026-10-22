import type { RunGraph, RunStep } from "./runs-api";

/** One step of a run as the run page shows it: the run's own version of the step and its result. */
export type RunStepView = {
  order: number;
  /** The step's label in the version the run used. */
  label: string;
  /** The freshest status: the content-free graph's, else the step result's. */
  status: string | null;
  outputType: string | null;
  /** The step's audited result, when it has one. */
  result: RunStep | null;
};

/**
 * The run's steps in order, from the run-pinned graph (labels and the
 * freshest statuses, content free) and the audited step results. A result
 * without a graph node still shows, so nothing the core returned is hidden.
 */
export function runStepViews(
  graph: Pick<RunGraph, "nodes"> | null | undefined,
  steps: readonly RunStep[] | null | undefined
): RunStepView[] {
  const results = new Map((steps ?? []).map((step) => [step.step_order, step]));
  const views: RunStepView[] = [];
  const seen = new Set<number>();
  for (const node of graph?.nodes ?? []) {
    if (typeof node.step_order !== "number" || seen.has(node.step_order)) continue;
    seen.add(node.step_order);
    const result = results.get(node.step_order) ?? null;
    views.push({
      order: node.step_order,
      label: node.label,
      status: node.run_status ?? result?.status ?? null,
      outputType: node.output_type ?? null,
      result
    });
  }
  for (const step of steps ?? []) {
    if (seen.has(step.step_order)) continue;
    seen.add(step.step_order);
    views.push({
      order: step.step_order,
      label: "",
      status: step.status,
      outputType: null,
      result: step
    });
  }
  return views.sort((a, b) => a.order - b.order);
}

/**
 * What the content-free reads say about a run: its revision and each step's
 * status. When it changes, the run moved on and its audited detail and step
 * results are read again; while it stays the same they are not.
 */
export function progressSignature(
  status: { revision: number; status: string } | null | undefined,
  graph: Pick<RunGraph, "nodes"> | null | undefined
): string {
  const steps = (graph?.nodes ?? [])
    .filter((node) => typeof node.step_order === "number")
    .map((node) => `${node.step_order}=${node.run_status ?? ""}`)
    .join(",");
  return `${status?.revision ?? ""}:${status?.status ?? ""}:${steps}`;
}

/** The text a step produced, when its output is text. */
export function outputText(payload: RunStep["output_payload_json"]): string | null {
  const text = payload?.text;
  return typeof text === "string" ? text : null;
}

/** The structured value a step produced, when its output is JSON. */
export function outputStructured(payload: RunStep["output_payload_json"]): unknown {
  if (!payload || !("structured" in payload)) return undefined;
  return payload.structured;
}

/** Tokens a step or a run used, or null when the core counted none. */
export function tokenTotal(
  input: number | null | undefined,
  output: number | null | undefined
): number | null {
  if (input == null && output == null) return null;
  return (input ?? 0) + (output ?? 0);
}
