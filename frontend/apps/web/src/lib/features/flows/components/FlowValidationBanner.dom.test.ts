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

    // The raw server sentence stays folded behind the technical details
    // disclosure and appears exactly once when opened, never as the primary copy.
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_validation_technical_details() })
    );
    const raw = screen.getAllByText(RAW_STEP_SENTENCE);
    expect(raw).toHaveLength(1);
    expect(raw[0].closest('[data-slot="collapsible-content"]')).not.toBeNull();

    // The action targets the offending step.
    await fireEvent.click(screen.getByRole("button", { name: m.flow_validation_go_to_step() }));
    expect(onNavigateToStep).toHaveBeenCalledWith("step-3");
  });

  it("keeps the raw detail for flow-scoped translated issues", async () => {
    const errors = new Map([["flow:server:flow_review_policy_invalid", [RAW_FLOW_SENTENCE]]]);

    render(FlowValidationBanner, { errors, steps: [], isExpanded: true });

    expect(screen.getByText(m.flow_validation_msg_review_policy_invalid())).toBeTruthy();
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_validation_technical_details() })
    );
    const raw = screen.getAllByText(RAW_FLOW_SENTENCE);
    expect(raw).toHaveLength(1);
    expect(raw[0].closest('[data-slot="collapsible-content"]')).not.toBeNull();
  });
});

function bindingSteps(): FlowStep[] {
  return [
    { ...makeStep(), id: "step-1", step_order: 1, user_description: "Source", output_type: "text" },
    {
      ...makeStep(),
      id: "step-2",
      step_order: 2,
      user_description: "Facts",
      output_type: "json",
      output_contract: { type: "object", properties: { title: { type: "string" } } }
    },
    { ...makeStep(), input_bindings: { question: "{{step_9}}" } },
    { ...makeStep(), id: "step-4", step_order: 4, user_description: "Later", output_type: "text" }
  ];
}

it("offers earlier step outputs for the exact server binding and dispatches the selection", async () => {
  const onRepairReference = vi.fn();
  const code = "flow_input_binding_unknown_step_order";
  render(FlowValidationBanner, {
    errors: new Map([[`flow:server:${code}:3`, ["Unknown step"]]]),
    steps: bindingSteps(),
    repairIssue: { code, stepOrder: 3, field: "input_bindings.question", reference: "step_9" },
    onRepairReference,
    isExpanded: true
  });
  expect(
    screen.getByText(m.flow_validation_replace_reference_from({ token: "step_9" }))
  ).toBeTruthy();
  const select = screen.getByRole("button", { name: m.flow_validation_replace_reference() });
  expect(select.textContent).toContain(m.flow_validation_replace_reference());
  expect(onRepairReference).not.toHaveBeenCalled();
  await fireEvent.keyDown(select, { key: "Enter" });
  const options = await screen.findAllByRole("option");
  expect(options.map((option) => option.textContent?.trim())).toEqual([
    m.flow_validation_replace_reference_option({ step: "1", name: "Source" }),
    m.flow_validation_replace_reference_option_field({ step: "2", name: "Facts", field: "title" })
  ]);
  expect(options.every((option) => option.getAttribute("aria-selected") !== "true")).toBe(true);
  await fireEvent.pointerUp(options[1], { pointerType: "mouse", button: 0 });
  expect(onRepairReference).toHaveBeenCalledExactlyOnceWith({
    stepId: "step-3",
    target: { location: { kind: "question" }, token: "step_9" },
    option: {
      key: "step_2:structured:title",
      stepRef: "step_2",
      sourceStepOrder: 2,
      sourceStepName: "Facts",
      output: "structured",
      fieldPath: "title",
      schemaType: "string",
      description: null
    }
  });
});

it.each([
  {
    code: "flow_input_binding_runtime_input_unused",
    order: 3,
    steps: bindingSteps(),
    repairOrder: 3
  },
  {
    code: "flow_input_binding_unknown_step_order",
    order: 1,
    steps: [{ ...makeStep(), step_order: 1, input_bindings: { question: "{{step_9}}" } }],
    repairOrder: 1
  },
  { code: "flow_input_binding_unknown_step_order", order: 3, steps: bindingSteps(), repairOrder: 4 }
])(
  "hides repair for unrelated issues, unavailable options, or mismatched identity: $code/$order/$repairOrder",
  ({ code, order, steps, repairOrder }) => {
    render(FlowValidationBanner, {
      errors: new Map([[`flow:server:${code}:${order}`, ["Issue"]]]),
      steps,
      repairIssue: {
        code,
        stepOrder: repairOrder,
        field: "input_bindings.question",
        reference: "step_9"
      },
      onRepairReference: vi.fn(),
      isExpanded: true
    });
    expect(
      screen.queryByRole("button", { name: m.flow_validation_replace_reference() })
    ).toBeNull();
  }
);

it("scans every step under the flow-wide deleted-reference issue and labels each repair", async () => {
  const steps = bindingSteps();
  steps[0].input_bindings = { question: "{{step_8_deleted}}" };
  steps[1].input_bindings = { question: "{{step_8_deleted.output.text}}" };
  steps[2].input_bindings = {
    question: "{{step_9_deleted}}",
    source_refs: [{ step_ref: "step_8_deleted", output: "text" }]
  };
  const onRepairReference = vi.fn();
  const { rerender } = render(FlowValidationBanner, {
    errors: new Map([["flow:deleted-step-reference", ["Removed step"]]]),
    steps,
    onRepairReference,
    isExpanded: true
  });
  expect(screen.getByText(m.flow_validation_msg_deleted_step_reference())).toBeTruthy();
  expect(
    screen.getByText(m.flow_validation_replace_reference_option({ step: "2", name: "Facts" }))
  ).toBeTruthy();
  expect(
    screen.getAllByText(
      m.flow_validation_replace_reference_option({ step: "3", name: "Sammanfatta underlaget" })
    )
  ).toHaveLength(2);
  const selects = screen.getAllByRole("button", { name: m.flow_validation_replace_reference() });
  expect(selects).toHaveLength(3);
  await fireEvent.keyDown(selects[2], { key: "Enter" });
  const option = await screen.findByRole("option", {
    name: m.flow_validation_replace_reference_option({ step: "1", name: "Source" })
  });
  await fireEvent.pointerUp(option, { pointerType: "mouse", button: 0 });
  expect(onRepairReference).toHaveBeenCalledExactlyOnceWith({
    stepId: "step-3",
    target: { location: { kind: "source_ref", index: 0 }, token: "step_8_deleted" },
    option: {
      key: "step_1:text:*",
      stepRef: "step_1",
      sourceStepOrder: 1,
      sourceStepName: "Source",
      output: "text",
      fieldPath: null,
      schemaType: null,
      description: null
    }
  });
  await rerender({ steps: steps.map((step) => ({ ...step, input_bindings: null })) });
  expect(screen.queryByRole("button", { name: m.flow_validation_replace_reference() })).toBeNull();
});

it.each([
  {
    restriction: "item template",
    input_contract: null,
    ref: { step_ref: "step_9", output: "structured", field_path: "items", item_template: "{title}" }
  },
  {
    restriction: "input contract",
    input_contract: { type: "object", properties: { title: { type: "string" } } },
    ref: { step_ref: "step_9", output: "structured", field_path: "title" }
  }
])(
  "shows the dangling token without a select for a source ref with $restriction",
  ({ input_contract, ref }) => {
    const steps = bindingSteps();
    steps[2] = { ...steps[2], input_contract, input_bindings: { source_refs: [ref] } };
    const code = "flow_input_binding_future_step_reference";
    render(FlowValidationBanner, {
      errors: new Map([[`flow:server:${code}:3`, ["Issue"]]]),
      steps,
      repairIssue: {
        code,
        stepOrder: 3,
        field: "input_bindings.source_refs[0].step_ref",
        reference: "step_9"
      },
      onRepairReference: vi.fn(),
      isExpanded: true
    });
    expect(
      screen.getByText(m.flow_validation_replace_reference_from({ token: "step_9" }))
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: m.flow_validation_replace_reference() })
    ).toBeNull();
  }
);
