// Copyright (c) 2026 Sundsvalls Kommun

import type { FlowDraftSpecCore, StepSpec } from "./protocol";

/** Create-mode plans carry no server diff (`proposal.edit` is null), so a
 *  change request's "Uppdaterat" markers are computed client-side by comparing
 *  the plan that was on screen with the plan that replaced it.
 *
 *  Identity is the step NAME, not `plan_step_ref`: the backend stamps refs
 *  positionally on every compile (`make_plan_step_ref(index)` →
 *  `step_a`, `step_b`, …) and re-stamps preserved steps, so a step inserted at
 *  the top renames every ref below it. The backend's own edit diff strips both
 *  refs before comparing for the same reason. A renamed step therefore reads as
 *  changed — which is what the user sees anyway.
 */
export function getRevisedStepRefs(
  previous: FlowDraftSpecCore | null | undefined,
  next: FlowDraftSpecCore
): ReadonlySet<string> {
  if (!previous) return new Set();

  const remaining = new Map<string, StepSpec[]>();
  for (const step of previous.steps) {
    const bucket = remaining.get(step.name);
    if (bucket) bucket.push(step);
    else remaining.set(step.name, [step]);
  }

  const revised = new Set<string>();
  for (const step of next.steps) {
    const bucket = remaining.get(step.name);
    const match = bucket?.shift();
    if (!match || comparableStep(match) !== comparableStep(step)) {
      revised.add(step.plan_step_ref);
    }
  }
  return revised;
}

/** Every field the user can see or the runtime acts on, minus the two identity
 *  refs the backend regenerates per compile. */
function comparableStep(step: StepSpec): string {
  const { plan_step_ref: _planRef, existing_step_ref: _existingRef, ...rest } = step;
  return stableStringify(rest);
}

/** Key order is an artifact of serialization, never a plan change. */
function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, entryValue]) => entryValue !== undefined)
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
    .map(([key, entryValue]) => `${JSON.stringify(key)}:${stableStringify(entryValue)}`);
  return `{${entries.join(",")}}`;
}
