import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import type { FlowStep } from "@eneo/eneo-js";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowValidationBanner from "./FlowValidationBanner.svelte";

afterEach(() => {
  cleanup();
});

const RAW_STEP_SENTENCE =
  "Step 3: explicit question bindings must reference step_input.* when runtime input is enabled.";
const RAW_FLOW_SENTENCE = "Review policy configuration is invalid for this flow.";

function makeStep(): FlowStep {
  return {
    id: "step-3",
    step_order: 3,
    user_description: "Sammanfatta underlaget",
    assistant_id: "assistant-3"
  } as FlowStep;
}

describe("FlowValidationBanner server issues", () => {
  it("shows translated copy first, keeps the raw sentence as technical detail, and navigates to the step", async () => {
    const onNavigateToStep = vi.fn();
    const errors = new Map([
      ["flow:server:flow_input_binding_runtime_input_unused:3", [RAW_STEP_SENTENCE]]
    ]);

    render(FlowValidationBanner, {
      errors,
      steps: [makeStep()],
      onNavigateToStep,
      isExpanded: true
    });

    // The translated sentence is the primary message.
    expect(
      screen.getByText(m.flow_validation_msg_input_binding_runtime_input_unused())
    ).toBeTruthy();

    // The raw server sentence appears exactly once, inside the technical
    // details disclosure — never as the primary copy.
    const raw = screen.getAllByText(RAW_STEP_SENTENCE);
    expect(raw).toHaveLength(1);
    expect(raw[0].closest("details")).not.toBeNull();
    expect(screen.getByText(m.flow_validation_technical_details())).toBeTruthy();

    // The action targets the offending step.
    await fireEvent.click(screen.getByRole("button", { name: m.flow_validation_go_to_step() }));
    expect(onNavigateToStep).toHaveBeenCalledWith("step-3");
  });

  it("keeps the raw detail for flow-scoped translated issues", () => {
    const errors = new Map([["flow:server:flow_review_policy_invalid", [RAW_FLOW_SENTENCE]]]);

    render(FlowValidationBanner, { errors, steps: [], isExpanded: true });

    expect(screen.getByText(m.flow_validation_msg_review_policy_invalid())).toBeTruthy();
    const raw = screen.getAllByText(RAW_FLOW_SENTENCE);
    expect(raw).toHaveLength(1);
    expect(raw[0].closest("details")).not.toBeNull();
  });
});
