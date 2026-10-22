import type { Schema } from "@/lib/api/models";
import type { RunError } from "./runs-api";

type StepPhase = Schema<"FlowStepPhase">;

/**
 * What a failed run's error says beyond its catalog sentence, as guidance a
 * person can act on: where the run stopped, what a timed-out step was doing
 * and how far it got, whether a provider or a tool may already have done
 * the work, what a tool or the transcription service said, and whether
 * running again unchanged can help. Read from the error's typed `details`
 * and `retryable`, never from its message.
 */
export type FailureFact =
  | { kind: "stopped_at"; order: number; name: string | null }
  | { kind: "phase"; phase: StepPhase }
  | { kind: "progress"; completed: number; total: number }
  | { kind: "provider_may_have_finished" }
  | { kind: "tool_may_have_acted" }
  | { kind: "tool_said"; text: string }
  | { kind: "service_said"; text: string }
  | { kind: "retry"; retryable: boolean };

const PHASES: ReadonlySet<string> = new Set<StepPhase>([
  "input_resolution",
  "transcription",
  "retrieval",
  "provider_request",
  "mapped_item",
  "finalization",
  "step_execution"
]);

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function failureFacts(
  error: Pick<RunError, "step_order" | "details" | "retryable">
): FailureFact[] {
  const facts: FailureFact[] = [];
  const details = error.details ?? {};
  if (typeof error.step_order === "number") {
    facts.push({
      kind: "stopped_at",
      order: error.step_order,
      name: text(details.step_description)
    });
  }
  if (details.phase && PHASES.has(details.phase)) {
    facts.push({ kind: "phase", phase: details.phase });
  }
  const completed = count(details.completed_items);
  const total = count(details.total_items);
  if (completed !== null && total !== null && total > 0) {
    facts.push({ kind: "progress", completed, total });
  }
  if (details.provider_work_may_have_completed) facts.push({ kind: "provider_may_have_finished" });
  if (details.tool_call_possible) facts.push({ kind: "tool_may_have_acted" });
  const toolText = text(details.tool_error_text);
  if (toolText) facts.push({ kind: "tool_said", text: toolText });
  const serviceText = text(details.transcription_service_reason);
  if (serviceText) facts.push({ kind: "service_said", text: serviceText });
  // A tool that may have acted already is the reason not to retry; saying
  // "the same error again" as well would mislead.
  if (!details.tool_call_possible) facts.push({ kind: "retry", retryable: error.retryable });
  return facts;
}
