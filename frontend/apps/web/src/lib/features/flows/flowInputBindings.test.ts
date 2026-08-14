import { describe, expect, it } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import {
  getFlowStepEffectiveInputSources,
  getFlowInputMaterialOptions,
  getInputBindingSourceRefs,
  hasDeletedInputBindingSourceRefs,
  parseFlowInputBindings,
  setInputBindingQuestion,
  setInputBindingSourceRefs
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
            label: "Title",
            item_template: "- {name}: {value}"
          }
        ]
      })
    ).toEqual([
      {
        stepRef: "step_1",
        output: "text",
        fieldPath: null,
        label: "Original text",
        itemTemplate: null
      },
      {
        stepRef: "step_2",
        output: "structured",
        fieldPath: "summary.title",
        label: "Title",
        itemTemplate: "- {name}: {value}"
      }
    ]);
  });

  it("fails closed when bindings contain unsupported or malformed data", () => {
    expect(parseFlowInputBindings({ source_refs: "step_1" }).status).toBe("invalid");
    expect(parseFlowInputBindings({ source_refs: null }).status).toBe("invalid");
    expect(
      parseFlowInputBindings({
        source_refs: [{ step_ref: "step_1", output: "text", field_path: "summary" }]
      }).status
    ).toBe("invalid");
    expect(parseFlowInputBindings({ source_refs: [], hidden_mode: true }).status).toBe("invalid");
  });

  it("serializes edited refs without losing the custom text or advanced ref fields", () => {
    const result = setInputBindingSourceRefs(
      {
        question: "Skriv en kort rapport.",
        source_refs: [
          {
            step_ref: "step_1",
            output: "structured",
            field_path: "participants",
            label: "Deltagare",
            item_template: "- {name}"
          }
        ]
      },
      [
        {
          stepRef: "step_1",
          output: "structured",
          fieldPath: "participants",
          label: "Deltagare",
          itemTemplate: "- {name}"
        },
        {
          stepRef: "step_2",
          output: "text",
          fieldPath: null,
          label: null,
          itemTemplate: null
        }
      ]
    );

    expect(result).toEqual({
      status: "updated",
      inputBindings: {
        question: "Skriv en kort rapport.",
        source_refs: [
          {
            step_ref: "step_1",
            output: "structured",
            field_path: "participants",
            label: "Deltagare",
            item_template: "- {name}"
          },
          { step_ref: "step_2", output: "text" }
        ]
      }
    });
  });

  it("blocks source edits when the persisted binding shape is not understood", () => {
    expect(setInputBindingSourceRefs({ source_refs: [], hidden_mode: true }, [])).toEqual({
      status: "blocked"
    });
  });

  it("updates custom text through the same closed binding contract", () => {
    expect(
      setInputBindingQuestion(
        {
          source_refs: [{ step_ref: "step_1", output: "structured", field_path: "summary" }]
        },
        "  Skriv en kort rapport.  "
      )
    ).toEqual({
      status: "updated",
      inputBindings: {
        question: "Skriv en kort rapport.",
        source_refs: [{ step_ref: "step_1", output: "structured", field_path: "summary" }]
      }
    });
    expect(setInputBindingQuestion({ hidden_mode: true }, "Text")).toEqual({
      status: "blocked"
    });
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
        label: "Original analys",
        itemTemplate: null
      },
      {
        kind: "source_ref",
        stepRef: "step_2",
        sourceStepOrder: 2,
        sourceStepName: "Extrahera fakta",
        output: "structured",
        fieldPath: "date",
        label: null,
        itemTemplate: null
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

  it("does not invent implicit material when the saved binding is invalid", () => {
    const steps = [
      makeStep(1, { user_description: "Transkribera" }),
      makeStep(2, {
        user_description: "Sammanfatta",
        input_bindings: { hidden_mode: true } as never
      })
    ];

    expect(getFlowStepEffectiveInputSources(steps[1], steps)).toEqual([]);
  });

  it("describes custom text as the effective material instead of claiming the implicit source", () => {
    const steps = [
      makeStep(1, { user_description: "Transkribera" }),
      makeStep(2, {
        user_description: "Sammanfatta",
        input_bindings: { question: "Arbeta bara med besluten i texten." } as never
      })
    ];

    expect(getFlowStepEffectiveInputSources(steps[1], steps)).toEqual([
      { kind: "custom_question" }
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
        label: null,
        itemTemplate: null
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

describe("getFlowInputMaterialOptions", () => {
  it("offers whole prior results and only contract-backed JSON fields", () => {
    const steps = [
      makeStep(1, {
        user_description: "Strukturera samtalet",
        output_type: "json",
        output_contract: {
          type: "object",
          properties: {
            summary: { type: "string", description: "Kort sammanfattning" },
            participants: { type: "array" }
          }
        }
      }),
      makeStep(2, { user_description: "Skriv rapport" }),
      makeStep(3, { user_description: "Framtida steg" })
    ];

    expect(getFlowInputMaterialOptions(2, steps)).toEqual([
      {
        key: "step_1:structured:*",
        stepRef: "step_1",
        sourceStepOrder: 1,
        sourceStepName: "Strukturera samtalet",
        output: "structured",
        fieldPath: null,
        schemaType: null,
        description: null
      },
      {
        key: "step_1:structured:summary",
        stepRef: "step_1",
        sourceStepOrder: 1,
        sourceStepName: "Strukturera samtalet",
        output: "structured",
        fieldPath: "summary",
        schemaType: "string",
        description: "Kort sammanfattning"
      },
      {
        key: "step_1:structured:participants",
        stepRef: "step_1",
        sourceStepOrder: 1,
        sourceStepName: "Strukturera samtalet",
        output: "structured",
        fieldPath: "participants",
        schemaType: "array",
        description: null
      }
    ]);
  });

  it("does not offer a free-form JSON result that the backend cannot bind safely", () => {
    const steps = [
      makeStep(1, {
        user_description: "Fritt JSON-resultat",
        output_type: "json",
        output_contract: null
      }),
      makeStep(2, { user_description: "Skriv rapport" })
    ];

    expect(getFlowInputMaterialOptions(2, steps)).toEqual([]);
  });
});
