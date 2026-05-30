import { describe, expect, it } from "vitest";
import type { FlowDraftSpecCore, StepSpec } from "./protocol";
import { draftSpecToFlow, planStepsToFlowSteps } from "./aiBuilderDraftFlow";

function makeStep(overrides: Partial<StepSpec> = {}): StepSpec {
  return {
    plan_step_ref: "step_a",
    name: "Transkribera ljud",
    assistant_spec: { instructions: "Transkribera den uppladdade ljudfilen." },
    input_source: "flow_input",
    ...overrides
  };
}

describe("planStepsToFlowSteps", () => {
  it("maps a draft step onto the editor's FlowStep shape", () => {
    const [flowStep] = planStepsToFlowSteps([
      makeStep({
        plan_step_ref: "step_b",
        name: "Skriv PDF-rapport",
        input_source: "previous_step",
        input_type: "text",
        output_type: "pdf",
        output_mode: "pass_through"
      })
    ]);

    expect(flowStep).toMatchObject({
      id: "step_b",
      user_description: "Skriv PDF-rapport",
      step_order: 1,
      input_source: "previous_step",
      input_type: "text",
      output_type: "pdf",
      output_mode: "pass_through"
    });
  });

  it("numbers steps from their array position", () => {
    const flowSteps = planStepsToFlowSteps([
      makeStep({ plan_step_ref: "step_a" }),
      makeStep({ plan_step_ref: "step_b" }),
      makeStep({ plan_step_ref: "step_c" })
    ]);

    expect(flowSteps.map((step) => step.step_order)).toEqual([1, 2, 3]);
    expect(flowSteps.map((step) => step.id)).toEqual(["step_a", "step_b", "step_c"]);
  });

  it("uses an empty assistant_id so the canvas never fetches live assistant metadata", () => {
    // FlowGraph only loads assistant meta for non-empty ids; a draft has no real
    // assistant yet, so the sentinel keeps the canvas a pure local render.
    const [flowStep] = planStepsToFlowSteps([makeStep()]);

    expect(flowStep.assistant_id).toBe("");
  });

  it("applies the backend spec defaults for optional shape fields", () => {
    const [flowStep] = planStepsToFlowSteps([
      makeStep({
        input_type: undefined,
        output_type: undefined,
        output_mode: undefined,
        mcp_policy: undefined
      })
    ]);

    expect(flowStep.input_type).toBe("text");
    expect(flowStep.output_type).toBe("text");
    expect(flowStep.output_mode).toBe("pass_through");
    expect(flowStep.mcp_policy).toBe("inherit");
  });

  it("preserves wiring fields so data-flow edges stay accurate", () => {
    const [flowStep] = planStepsToFlowSteps([
      makeStep({
        input_source: "all_previous_steps",
        input_bindings: { source_step: "step_a" },
        input_contract: { kind: "json" },
        output_contract: { kind: "pdf" }
      })
    ]);

    expect(flowStep.input_source).toBe("all_previous_steps");
    expect(flowStep.input_bindings).toEqual({ source_step: "step_a" });
    expect(flowStep.input_contract).toEqual({ kind: "json" });
    expect(flowStep.output_contract).toEqual({ kind: "pdf" });
  });
});

describe("draftSpecToFlow", () => {
  function makeSpec(overrides: Partial<FlowDraftSpecCore> = {}): FlowDraftSpecCore {
    return {
      flow_name: "Mötesanteckningar till PDF",
      flow_description: "Ljud in, sammanhängande PDF ut.",
      steps: [makeStep()],
      ...overrides
    };
  }

  it("wraps the draft spec in a synthetic Flow for FlowGraph", () => {
    const flow = draftSpecToFlow(makeSpec());

    expect(flow.name).toBe("Mötesanteckningar till PDF");
    expect(flow.description).toBe("Ljud in, sammanhängande PDF ut.");
    expect(flow.steps).toHaveLength(1);
    expect(flow.steps[0]?.id).toBe("step_a");
  });

  it("marks the synthetic flow as unpublished so the canvas is never read-only", () => {
    // FlowGraph treats a non-null published_version as a locked, read-only flow.
    const flow = draftSpecToFlow(makeSpec());

    expect(flow.published_version).toBeNull();
  });

  it("renders an empty draft as a flow with no steps", () => {
    const flow = draftSpecToFlow(makeSpec({ steps: [] }));

    expect(flow.steps).toEqual([]);
  });
});
