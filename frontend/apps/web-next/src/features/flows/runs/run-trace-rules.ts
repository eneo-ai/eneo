import { EneoApiError } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

/**
 * Pure rules for a run's trace on the run page: what a raw export's reason
 * must be, which recovery an oversized export points to, and how the step
 * attempts and provider calls group. Who the trace is offered to is the
 * core's answer, the run detail's `evidence_access`.
 */

type Attempt = Schema<"FlowStepAttemptPublic">;

/** The reason the core uses for a redacted export; a raw export must give its own. */
export const DEFAULT_EXPORT_REASON = "support_debug";
export const EXPORT_REASON_MIN_LENGTH = 3;
export const EXPORT_REASON_MAX_LENGTH = 500;

/** Why a raw export's reason would be refused, or null when the core takes it. */
export function rawReasonProblem(reason: string): "required" | "too_long" | null {
  const trimmed = reason.trim();
  if (trimmed.length < EXPORT_REASON_MIN_LENGTH || trimmed === DEFAULT_EXPORT_REASON) {
    return "required";
  }
  return trimmed.length > EXPORT_REASON_MAX_LENGTH ? "too_long" : null;
}

/**
 * Where to look instead when the core refuses an export as too large: the
 * trace on the page for passage limits, the provider-call pages for too
 * many calls, or nothing more specific. Null for any other refusal.
 */
export function exportRecovery(error: unknown): "trace" | "provider_calls" | "generic" | null {
  if (!(error instanceof EneoApiError) || error.reason !== "flow_evidence_export_too_large") {
    return null;
  }
  switch (error.context?.limit) {
    case "recorded_passage_bytes":
    case "stored_provenance_bytes":
    case "corrupt_passage_evidence":
      return "trace";
    case "provider_call_events":
      return "provider_calls";
    default:
      return "generic";
  }
}

/** The attempts of each step, by step order, each step's attempts in order. */
export function attemptsByStep(attempts: readonly Attempt[]): Map<number, Attempt[]> {
  const grouped = new Map<number, Attempt[]>();
  for (const attempt of [...attempts].sort(
    (a, b) => a.step_order - b.step_order || a.attempt_no - b.attempt_no
  )) {
    grouped.set(attempt.step_order, [...(grouped.get(attempt.step_order) ?? []), attempt]);
  }
  return grouped;
}

/** How long an attempt took, or null while it runs or when its clock is unreadable. */
export function attemptDurationMs(attempt: Pick<Attempt, "started_at" | "finished_at">) {
  if (!attempt.finished_at) return null;
  const ms = Date.parse(attempt.finished_at) - Date.parse(attempt.started_at);
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}
