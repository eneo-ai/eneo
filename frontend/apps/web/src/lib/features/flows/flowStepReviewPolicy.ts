import type { FlowStep } from "@eneo/eneo-js";

import { hasOutboundDeliveryOutputMode } from "./flowStepTypes";

export const FLOW_STEP_REVIEW_MODE_CHOICES = ["none", "view", "edit"] as const;

export type FlowStepReviewModeChoice = (typeof FLOW_STEP_REVIEW_MODE_CHOICES)[number];

export function parseFlowStepReviewModeChoice(value: string): FlowStepReviewModeChoice {
  return value === "view" || value === "edit" ? value : "none";
}

export function getFlowStepReviewModeChoice(
  step: Pick<FlowStep, "review_policy">
): FlowStepReviewModeChoice {
  const mode = step.review_policy?.mode;
  return mode === "view" || mode === "edit" ? mode : "none";
}

export function buildFlowStepReviewPolicyPatch(
  mode: FlowStepReviewModeChoice
): Pick<FlowStep, "review_policy"> {
  return {
    review_policy: mode === "none" ? null : { mode }
  };
}

export function isFlowStepReviewPolicySupported(step: Pick<FlowStep, "output_mode">): boolean {
  return !hasOutboundDeliveryOutputMode(step.output_mode);
}

export function sanitizeFlowStepReviewPolicy(step: FlowStep): FlowStep {
  return isFlowStepReviewPolicySupported(step) ? step : { ...step, review_policy: null };
}
