import type { FlowRetentionHold } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

export const HOLD_REASON_MAX = 512;
export const HOLD_RUNS_MAX = 100;

/** yyyy-mm-dd of a local calendar day, the value of an <input type="date">. */
export function localDate(value: Date): string {
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${value.getFullYear()}-${month}-${day}`;
}

export function addLocalDays(value: string, days: number): string {
  const [year, month, day] = value.split("-").map(Number);
  return localDate(new Date(year, month - 1, day + days));
}

/** A chosen date means "until that local day ends". */
export function endOfLocalDay(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day, 23, 59, 59, 999).toISOString();
}

/**
 * The latest review date the server accepts: the end of that local day must be
 * at most maxDays * 24 h after `now`. Walking back from the far end handles a
 * daylight-saving change inside the window.
 */
export function latestReviewDate(now: Date, maxDays: number): string {
  const limit = now.getTime() + maxDays * 24 * 60 * 60 * 1000;
  let candidate = addLocalDays(localDate(now), maxDays);
  while (Date.parse(endOfLocalDay(candidate)) > limit) {
    candidate = addLocalDays(candidate, -1);
  }
  return candidate;
}

export function isValidReason(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.length >= 1 && trimmed.length <= HOLD_REASON_MAX;
}

export type HoldState = "active" | "released" | "ended";

export function holdState(hold: FlowRetentionHold): HoldState {
  if (hold.active) return "active";
  return hold.released_at ? "released" : "ended";
}

export function holdScopeLabel(hold: FlowRetentionHold): string {
  return hold.flow_run_id
    ? m.flow_retention_hold_scope_run({ run: hold.flow_run_id })
    : m.flow_retention_hold_scope_flow();
}

// The typed refusal code is in the response body; EneoError.code is numeric.
export function holdErrorCode(error: unknown): string | null {
  if (typeof error !== "object" || error === null) return null;
  const response = (error as { response?: unknown }).response;
  if (typeof response !== "object" || response === null) return null;
  const code = (response as { code?: unknown }).code;
  return typeof code === "string" ? code : null;
}

/** Plain-language copy for the typed refusals of the hold routes; null for anything else. */
export function holdErrorMessage(error: unknown): string | null {
  switch (holdErrorCode(error)) {
    case "flow_retention_hold_run_not_in_flow":
      return m.flow_retention_hold_error_run_not_in_flow();
    case "flow_retention_hold_end_not_in_future":
      return m.flow_retention_hold_error_end_not_in_future();
    case "flow_retention_hold_review_out_of_range":
      return m.flow_retention_hold_error_review_out_of_range();
    case "flow_retention_hold_review_not_later":
      return m.flow_retention_hold_error_review_not_later();
    case "flow_retention_hold_not_active":
      return m.flow_retention_hold_error_not_active();
    case "flow_retention_hold_already_released":
      return m.flow_retention_hold_error_already_released();
    case "flow_retention_lock_busy":
      return m.flow_retention_hold_error_busy();
    case "retention_permission_required":
    case "retention_person_required":
      return m.flow_retention_hold_error_not_allowed();
    default:
      return null;
  }
}
