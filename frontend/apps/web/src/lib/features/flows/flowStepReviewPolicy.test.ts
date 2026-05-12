import { describe, expect, test } from "vitest";
import type { FlowStep } from "@intric/intric-js";

import {
  buildFlowStepReviewPolicyPatch,
  getFlowStepReviewModeChoice,
  isFlowStepReviewPolicySupported,
  parseFlowStepReviewModeChoice,
  sanitizeFlowStepReviewPolicy
} from "./flowStepReviewPolicy";

function makeStep(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: "step-1",
    assistant_id: "assistant-1",
    step_order: 1,
    user_description: "Step",
    input_source: "flow_input",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    mcp_policy: "inherit",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    review_policy: null,
    ...overrides
  } as FlowStep;
}

describe("flow step review policy", () => {
  test("reads the configured review mode", () => {
    expect(getFlowStepReviewModeChoice(makeStep({ review_policy: { mode: "view" } }))).toBe(
      "view"
    );
    expect(getFlowStepReviewModeChoice(makeStep({ review_policy: { mode: "edit" } }))).toBe(
      "edit"
    );
  });

  test("treats missing review policy as disabled", () => {
    expect(getFlowStepReviewModeChoice(makeStep({ review_policy: null }))).toBe("none");
  });

  test("builds review policy patches for disabled and enabled modes", () => {
    expect(buildFlowStepReviewPolicyPatch("none")).toEqual({ review_policy: null });
    expect(buildFlowStepReviewPolicyPatch("view")).toEqual({ review_policy: { mode: "view" } });
    expect(buildFlowStepReviewPolicyPatch("edit")).toEqual({ review_policy: { mode: "edit" } });
  });

  test("parses select values without leaking invalid strings into step state", () => {
    expect(parseFlowStepReviewModeChoice("view")).toBe("view");
    expect(parseFlowStepReviewModeChoice("edit")).toBe("edit");
    expect(parseFlowStepReviewModeChoice("other")).toBe("none");
  });

  test("disables review policy for outbound output steps", () => {
    expect(isFlowStepReviewPolicySupported(makeStep({ output_mode: "pass_through" }))).toBe(true);
    expect(isFlowStepReviewPolicySupported(makeStep({ output_mode: "transcribe_only" }))).toBe(
      true
    );
    expect(isFlowStepReviewPolicySupported(makeStep({ output_mode: "http_post" }))).toBe(false);
  });

  test("clears review policy when the step no longer supports review", () => {
    const result = sanitizeFlowStepReviewPolicy(
      makeStep({ output_mode: "http_post", review_policy: { mode: "edit" } })
    );

    expect(result.review_policy).toBeNull();
  });
});
