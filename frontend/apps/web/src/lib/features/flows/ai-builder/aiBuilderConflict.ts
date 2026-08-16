// Copyright (c) 2026 Sundsvalls Kommun

import type { AIBuilderError } from "./protocol";

/** What the user has to do about it, not which endpoint reported it.
 *  - `stale_revision`: the saved flow moved on under the plan.
 *  - `stale_plan`: the draft has a newer plan than the one on screen.
 *  - `send_in_progress`: another turn for this session is still running. */
export type AIBuilderConflictKind = "stale_revision" | "stale_plan" | "send_in_progress";

export interface AIBuilderConflict {
  kind: AIBuilderConflictKind;
}

interface ConflictInput {
  applyError: AIBuilderError | null;
  error: AIBuilderError | null;
  isConflict: boolean;
}

// Conflicts reach the client on two transports: the apply/create HTTP call and
// the SSE `error` frame of a running turn. Both carry the same public error
// shape, so one code table classifies them.
const CONFLICT_KIND_BY_CODE = new Map<string, AIBuilderConflictKind>([
  ["stale_revision", "stale_revision"],
  ["stale_plan_revision", "stale_plan"],
  ["session_latest_plan_update_conflict", "stale_plan"],
  ["session_send_in_progress", "send_in_progress"],
  ["session_send_lease_lost", "send_in_progress"],
  ["session_message_in_progress", "send_in_progress"],
  ["session_turn_idempotency_conflict", "send_in_progress"]
]);

export function classifyAIBuilderConflict({
  applyError,
  error,
  isConflict
}: ConflictInput): AIBuilderConflict | null {
  for (const candidate of [applyError, error]) {
    const kind = candidate ? CONFLICT_KIND_BY_CODE.get(candidate.code) : undefined;
    if (kind) return { kind };
  }
  // The driver's own stale-apply latch outlives the error it was set from.
  return isConflict ? { kind: "stale_revision" } : null;
}
