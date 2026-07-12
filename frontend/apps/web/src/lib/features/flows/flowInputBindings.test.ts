import { describe, expect, it } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import {
  getFlowStepEffectiveInputSources,
  getInputBindingSourceRefs,
  hasDeletedInputBindingSourceRefs
} from "./flowInputBindings";

function makeStep(stepOrder: number, overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: `step-${stepOrder}`,
    assistant_id: `assistant-${stepOrder}`,
    step_order: stepOrder,
    user_description: `Step ${stepOrder}`,
    input_source: stepOrder === 1 ? "flow_input" : "previous_step",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    ...overrides
  };
}

describe("getInputBindingSourceRefs", () => {
  it("parses valid typed source refs from persisted input bindings", () => {
    expect(
      getInputBindingSourceRefs({
        source_refs: [
          { step_ref: "step_1", output: "text", label: "Original text" },
          {
            step_ref: "step_2",
            output: "structured",
            field_path: "summary.title",
            label: "Title"
          }
        ]
      })
    ).toEqual([
      { stepRef: "step_1", output: "text", fieldPath: null, label: "Original text" },
      { stepRef: "step_2", output: "structured", fieldPath: "summary.title", label: "Title" }
    ]);
  });
});

describe("getFlowStepEffectiveInputSources", () => {
  it("describes typed source refs with their resolved step names", () => {
    const steps = [
      makeStep(1, { user_description: "Läs dokument" }),
      makeStep(2, { user_description: "Extrahera fakta" }),
      makeStep(3, {
        user_description: "Skriv rapport",
        input_bindings: {
          source_refs: [
            { step_ref: "step_1", output: "text", label: "Original analys" },
            { step_ref: "step_2", output: "structured", field_path: "date" }
          ]
        } as never
      })
    ];

    expect(getFlowStepEffectiveInputSources(steps[2], steps)).toEqual([
      {
        kind: "source_ref",
        stepRef: "step_1",
        sourceStepOrder: 1,
        sourceStepName: "Läs dokument",
        output: "text",
        fieldPath: null,
        label: "Original analys"
      },
      {
        kind: "source_ref",
        stepRef: "step_2",
        sourceStepOrder: 2,
        sourceStepName: "Extrahera fakta",
        output: "structured",
        fieldPath: "date",
        label: null
      }
    ]);
  });

  it("describes the implicit previous-step underlag when bindings are empty", () => {
    const steps = [
      makeStep(1, { user_description: "Transkribera" }),
      makeStep(2, { user_description: "Sammanfatta", input_bindings: null })
    ];

    expect(getFlowStepEffectiveInputSources(steps[1], steps)).toEqual([
      {
        kind: "implicit_previous_step",
        sourceStepOrder: 1,
        sourceStepName: "Transkribera"
      }
    ]);
  });

  it("describes deleted typed source refs as an explicit lifecycle state", () => {
    const steps = [
      makeStep(1, { user_description: "Läs dokument" }),
      makeStep(2, {
        user_description: "Skriv rapport",
        input_bindings: {
          source_refs: [{ step_ref: "step_1_deleted", output: "text" }]
        } as never
      })
    ];

    expect(getFlowStepEffectiveInputSources(steps[1], steps)).toEqual([
      {
        kind: "deleted_source",
        stepRef: "step_1_deleted",
        deletedStepOrder: 1,
        output: "text",
        fieldPath: null,
        label: null
      }
    ]);
  });
});

describe("hasDeletedInputBindingSourceRefs", () => {
  it("detects typed refs that were marked after deleting a source step", () => {
    expect(
      hasDeletedInputBindingSourceRefs({
        source_refs: [{ step_ref: "step_2_deleted", output: "text" }]
      })
    ).toBe(true);
  });
});
