import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { EneoError, type FlowStep } from "@eneo/eneo-js";
import { readable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";
import { flowStepFixture } from "$lib/features/flows/flowStepTestFixture";

import {
  describeClassificationRefusal,
  getValidationIssueMessage,
  parseServerValidationIdentity,
  type ClassificationRefusal
} from "$lib/features/flows/flowStepValidationMessages";

import FlowValidationBanner from "./FlowValidationBanner.svelte";

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: {
      currentSpace: readable({
        completion_models: [
          { id: "model-a", name: "model-a-name", nickname: "Modell A" },
          { id: "model-b", name: "Modell B", nickname: null }
        ]
      })
    }
  })
}));

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
    expect(onNavigateToStep).toHaveBeenCalledWith("step-3", null);
  });

  it("says a step needs a model when publish refuses a model step without one", async () => {
    // Kills: the refusal shown as its bare code instead of a sentence.
    const onNavigateToStep = vi.fn();
    const errors = new Map([
      [
        "flow:server:flow_assistant_model_provider_required:3",
        ["Step 3: Select a provider-backed model before publishing the flow."]
      ]
    ]);

    render(FlowValidationBanner, {
      errors,
      steps: [makeStep()],
      onNavigateToStep,
      isExpanded: true
    });

    expect(screen.getByText(m.flow_error_flow_assistant_model_provider_required())).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_validation_go_to_step() }));
    expect(onNavigateToStep).toHaveBeenCalledWith("step-3", null);
  });

  it("says a read of free-text run input on a form or upload flow is not received, not that a step is unusable", async () => {
    const raw =
      "Step 3: '{{ indata_text }}' reads the run's free-text input, but this flow's run collects only its form fields, so publish refuses a step that reads run text on such a flow.";
    const errors = new Map([["flow:server:flow_input_alias_not_received:3", [raw]]]);

    render(FlowValidationBanner, { errors, steps: [makeStep()], isExpanded: true });

    expect(screen.getByText(m.flow_validation_msg_input_alias_not_received())).toBeTruthy();
    expect(screen.queryByText(m.flow_validation_msg_input_binding_invalid_step())).toBeNull();
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_validation_technical_details() })
    );
    expect(screen.getAllByText(raw)).toHaveLength(1);
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

describe("FlowValidationBanner tool refusals", () => {
  const RAW_TOOL_SENTENCE = "Step 3: the server's own English sentence.";

  function renderRefusal(code: string, context: Record<string, unknown>) {
    const onNavigateToStep = vi.fn();
    const identity = parseServerValidationIdentity(
      new EneoError(RAW_TOOL_SENTENCE, "RESPONSE", 400, 0, {
        message: RAW_TOOL_SENTENCE,
        eneo_error_code: 0,
        code,
        context: { step_order: 3, ...context }
      })
    );
    render(FlowValidationBanner, {
      errors: new Map([
        [`flow:server:${identity?.code}:${identity?.stepOrder}`, [RAW_TOOL_SENTENCE]]
      ]),
      steps: [flowStepFixture({ id: "step-3", step_order: 3 })],
      repairIssue: identity,
      onNavigateToStep,
      isExpanded: true
    });
    return onNavigateToStep;
  }

  // Kills: the banner shows the code's generic sentence whatever `context.refusal`
  // says; a refusal value outside the enum is looked up as if it were one of its.
  it.each([
    { refusal: "server_disabled", sentence: () => m.flow_tool_refusal_server_disabled() },
    {
      refusal: "tool_switched_off_in_space",
      sentence: () => m.flow_tool_refusal_tool_switched_off_in_space()
    },
    {
      refusal: "a_level_this_client_lacks",
      sentence: () => m.flow_error_typed_io_tool_not_allowed()
    }
  ])("says on the step which level refuses the tool: $refusal", ({ refusal, sentence }) => {
    renderRefusal("typed_io_tool_not_allowed", {
      refusal,
      mcp_server_id: "server-1",
      tool_id: "tool-1"
    });

    expect(screen.getByText(sentence())).toBeTruthy();
    // Kills: the refusal is shown flow-wide, without the action that opens its step.
    expect(screen.getByRole("button", { name: m.flow_validation_go_to_step() })).toBeTruthy();
  });

  // Kills: an argument problem shows the code's generic sentence, or a sentence
  // chosen without the problem or without the argument's name.
  it("names the argument a refused tool configuration is about", async () => {
    const onNavigateToStep = renderRefusal("typed_io_tool_invalid_config", {
      issue_code: "flow_step_invalid",
      field: "input_config.tool.arguments.query",
      argument: "query",
      problem: "composed_text"
    });

    expect(
      screen.getByText(m.flow_tool_argument_composed_text({ argument: "query" }))
    ).toBeTruthy();
    // Kills: "Go to step" leaves the author at the top of the step, not at the argument.
    await fireEvent.click(screen.getByRole("button", { name: m.flow_validation_go_to_step() }));
    expect(onNavigateToStep).toHaveBeenCalledWith("step-3", {
      kind: "tool_argument",
      name: "query"
    });
  });

  // Kills: "Go to step" for a refused tool or an unreadable tool choice leaves
  // the author at the top of the step; a refusal about another setting of
  // the step lands on the picker.
  it.each([
    {
      code: "typed_io_tool_not_allowed",
      context: { refusal: "server_disabled" },
      focus: { kind: "tool" }
    },
    {
      code: "typed_io_tool_invalid_config",
      context: { field: "input_config.tool" },
      focus: { kind: "tool" }
    },
    { code: "typed_io_tool_invalid_config", context: { field: "input_type" }, focus: null }
  ])("asks to land where $code about $context is fixed", async ({ code, context, focus }) => {
    const onNavigateToStep = renderRefusal(code, context);

    await fireEvent.click(screen.getByRole("button", { name: m.flow_validation_go_to_step() }));
    expect(onNavigateToStep).toHaveBeenCalledWith("step-3", focus);
  });

  // Kills: the banner names only one of the missing arguments.
  it("names every argument a tool step is missing", () => {
    render(FlowValidationBanner, {
      errors: new Map([
        [
          "flow:step-config:tool_argument_missing:3",
          ["tool_argument_missing", "to_date", "from_date"]
        ]
      ]),
      steps: [flowStepFixture({ id: "step-3", step_order: 3 })],
      isExpanded: true
    });

    const names = new Intl.ListFormat(getLocale(), { type: "conjunction" }).format([
      "to_date",
      "from_date"
    ]);
    expect(screen.getByText(m.flow_tool_arguments_missing({ names }))).toBeTruthy();
  });

  // Kills: "Go to step" for a tool step's own issue leaves the author at the
  // top of the step instead of at the picker or at the argument the issue
  // names; an issue outside the tool section asks for a place in it.
  it.each([
    { code: "tool_missing_tool", subject: [], focus: { kind: "tool" } },
    {
      code: "tool_argument_missing",
      subject: ["query"],
      focus: { kind: "tool_argument", name: "query" }
    },
    {
      code: "tool_argument_missing",
      subject: ["to_date", "from_date"],
      focus: { kind: "tool_argument", name: "to_date" }
    },
    { code: "http_missing_url", subject: [], focus: null }
  ])("asks to land where the editor's issue $code is fixed", async ({ code, subject, focus }) => {
    const onNavigateToStep = vi.fn();
    render(FlowValidationBanner, {
      errors: new Map([[`flow:step-config:${code}:3`, [code, ...subject]]]),
      steps: [flowStepFixture({ id: "step-3", step_order: 3 })],
      onNavigateToStep,
      isExpanded: true
    });

    await fireEvent.click(screen.getByRole("button", { name: m.flow_validation_go_to_step() }));
    expect(onNavigateToStep).toHaveBeenCalledWith("step-3", focus);
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

describe("FlowValidationBanner security classification refusals", () => {
  const code = "flow_step_security_classification_mismatch";
  const RAW = "Step 3: assistant model does not meet the required security classification.";
  const refusal: ClassificationRefusal = {
    kind: "model_below_required",
    requiredLevel: 3,
    currentLevel: 2,
    cause: "reads",
    sourceStepOrders: [1],
    qualifyingModelIds: ["model-a", "model-b"]
  };
  const steps = [
    { ...makeStep(), id: "step-1", step_order: 1, user_description: "Transkribera" },
    makeStep()
  ];
  // The organisation's own classes name the levels the refusal carries.
  const classifications = [
    { name: "Intern", security_level: 2 },
    { name: "Konfidentiell", security_level: 3 }
  ];
  const names = {
    stepLabel: (order: number) => (order === 1 ? "Transkribera" : `Steg ${order}`),
    modelName: (id: string) => ({ "model-a": "Modell A", "model-b": "Modell B" })[id],
    className: (level: number) =>
      classifications.find((entry) => entry.security_level === level)?.name ?? ""
  };

  it("says which step is read, what the model is cleared for and which models to choose", async () => {
    const onNavigateToStep = vi.fn();
    render(FlowValidationBanner, {
      errors: new Map([[`flow:server:${code}:3`, [RAW]]]),
      steps,
      classifications,
      onNavigateToStep,
      repairIssue: { code, stepOrder: 3, field: null, reference: null, classification: refusal },
      isExpanded: true
    });

    expect(screen.getByText(describeClassificationRefusal(refusal, names))).toBeTruthy();
    expect(screen.getByText(/Modell A/)).toBeTruthy();
    expect(screen.getByText(/Modell B/)).toBeTruthy();

    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_validation_technical_details() })
    );
    expect(screen.getAllByText(RAW)).toHaveLength(1);
    await fireEvent.click(screen.getByRole("button", { name: m.flow_validation_go_to_step() }));
    expect(onNavigateToStep).toHaveBeenCalledWith("step-3", null);
  });

  it("falls back to the translated sentence for a refusal without facts", () => {
    render(FlowValidationBanner, {
      errors: new Map([[`flow:server:${code}:3`, [RAW]]]),
      steps,
      classifications,
      isExpanded: true
    });

    expect(screen.getByText(getValidationIssueMessage(code))).toBeTruthy();
  });

  it("does not show facts that belong to another refusal", () => {
    render(FlowValidationBanner, {
      errors: new Map([[`flow:server:${code}:3`, [RAW]]]),
      steps,
      classifications,
      repairIssue: {
        code: "flow_step_output_classification_write_down",
        stepOrder: 3,
        field: null,
        reference: null,
        classification: { ...refusal, kind: "output_write_down" }
      },
      isExpanded: true
    });

    expect(screen.getByText(getValidationIssueMessage(code))).toBeTruthy();
  });
});

it("shows the translated step limit refusal with the server sentence as detail", async () => {
  const code = "flow_step_limit_exceeded";
  const raw = "A flow can have at most 256 steps; this one has 257. Remove steps and try again.";
  render(FlowValidationBanner, {
    errors: new Map([[`flow:server:${code}`, [raw]]]),
    steps: [],
    isExpanded: true
  });

  expect(screen.getByText(getValidationIssueMessage(code))).toBeTruthy();
  await fireEvent.click(
    screen.getByRole("button", { name: m.flow_validation_technical_details() })
  );
  expect(screen.getAllByText(raw)).toHaveLength(1);
});
