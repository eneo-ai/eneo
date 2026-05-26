import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";

import type { Flow, FlowStep, Intric } from "@intric/intric-js";

import { createFlowEditor, getUnifiedFlowSaveStatus } from "./FlowEditor";

function makeFlow(metadataJson: Flow["metadata_json"] = null, overrides: Partial<Flow> = {}): Flow {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    tenant_id: "tenant-1",
    space_id: "space-1",
    name: "Flow",
    description: null,
    published_version: null,
    metadata_json: metadataJson,
    data_retention_days: null,
    created_at: null,
    updated_at: null,
    steps: [],
    ...overrides
  };
}

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
    mcp_policy: "inherit",
    ...overrides
  };
}

function makeIntric(
  overrides: {
    assistantGet?: (...args: unknown[]) => unknown;
    assistantUpdate?: (...args: unknown[]) => unknown;
    flowUpdate?: (...args: unknown[]) => unknown;
  } = {}
): Intric {
  return {
    files: {
      delete: vi.fn()
    },
    flows: {
      update: overrides.flowUpdate ?? vi.fn(),
      assistants: {
        create: vi.fn(),
        get: overrides.assistantGet ?? vi.fn(),
        update: overrides.assistantUpdate ?? vi.fn()
      }
    },
    assistants: {
      listPrompts: vi.fn()
    }
  } as unknown as Intric;
}

describe("FlowEditor metadata commands", () => {
  it("replaces form schema fields with persisted field shape", () => {
    const { metadataJson, hasUnsavedChanges } = renderEditorMetadata({
      operation: "replace-form",
      flow: makeFlow({
        wizard: { transcription_enabled: true },
        form_schema: { fields: [{ name: "old", type: "text", order: 1 }] }
      })
    });

    expect(metadataJson).toEqual({
      wizard: { transcription_enabled: true },
      form_schema: {
        fields: [
          { name: "titel", label: "titel", type: "text", required: true, order: 1 },
          {
            name: "val",
            label: "val",
            type: "select",
            required: false,
            order: 2,
            options: ["A"]
          }
        ]
      }
    });
    expect(hasUnsavedChanges).toBe(true);
  });

  it("keeps explicit empty form schema fields", () => {
    const { metadataJson, hasUnsavedChanges } = renderEditorMetadata({
      operation: "empty-form",
      flow: makeFlow({ owner: "wizard" })
    });

    expect(metadataJson).toEqual({
      owner: "wizard",
      form_schema: { fields: [] }
    });
    expect(hasUnsavedChanges).toBe(true);
  });

  it("patches wizard metadata while preserving existing wizard and metadata keys", () => {
    const { metadataJson, hasUnsavedChanges } = renderEditorMetadata({
      operation: "wizard",
      flow: makeFlow({
        owner: "wizard",
        wizard: {
          transcription_enabled: true,
          transcription_language: "sv"
        }
      })
    });

    expect(metadataJson).toEqual({
      owner: "wizard",
      wizard: {
        transcription_enabled: false,
        transcription_language: "sv",
        transcription_model: { id: "model-1" }
      }
    });
    expect(hasUnsavedChanges).toBe(true);
  });

  it("replaces invalid wizard metadata with the requested patch", () => {
    const { metadataJson, hasUnsavedChanges } = renderEditorMetadata({
      operation: "wizard",
      flow: makeFlow({
        owner: "wizard",
        wizard: "invalid"
      })
    });

    expect(metadataJson).toEqual({
      owner: "wizard",
      wizard: {
        transcription_enabled: false,
        transcription_model: { id: "model-1" }
      }
    });
    expect(hasUnsavedChanges).toBe(true);
  });
});

describe("getUnifiedFlowSaveStatus", () => {
  it("treats queued assistant saves as unsaved until the save completes", () => {
    expect(getUnifiedFlowSaveStatus("saved", "pending")).toBe("unsaved");
  });

  it("surfaces active assistant saves as saving", () => {
    expect(getUnifiedFlowSaveStatus("saved", "saving")).toBe("saving");
  });

  it("keeps saved only when both flow and assistant saves are settled", () => {
    expect(getUnifiedFlowSaveStatus("saved", "idle")).toBe("saved");
  });

  it("surfaces assistant save errors as unsaved", () => {
    expect(getUnifiedFlowSaveStatus("saved", "error")).toBe("unsaved");
  });
});

describe("FlowEditor basic settings commands", () => {
  it("sets the name while preserving neighboring fields", () => {
    const flow = makeFlow(
      { owner: "metadata" },
      { description: "Description", data_retention_days: 30 }
    );
    const editor = createFlowEditor({ flow, intric: makeIntric() });
    try {
      const originalSteps = get(editor.state.update).steps;

      editor.setName("Renamed flow");

      const { update, hasUnsavedChanges } = readEditorState(editor);
      expect(update.name).toBe("Renamed flow");
      expect(update.description).toBe("Description");
      expect(update.metadata_json).toEqual({ owner: "metadata" });
      expect(update.steps).toBe(originalSteps);
      expect(update.data_retention_days).toBe(30);
      expect(hasUnsavedChanges).toBe(true);
    } finally {
      editor.destroy();
    }
  });

  it("accepts an empty name while preserving publish-readiness behavior", () => {
    const editor = createFlowEditor({ flow: makeFlow(), intric: makeIntric() });
    try {
      editor.setName("");

      const { update, hasUnsavedChanges } = readEditorState(editor);
      expect(update.name).toBe("");
      expect(hasUnsavedChanges).toBe(true);
    } finally {
      editor.destroy();
    }
  });

  it("sets the description string while preserving neighboring fields", () => {
    const flow = makeFlow(
      { owner: "metadata" },
      { name: "Original name", description: "Original", data_retention_days: 14 }
    );
    const editor = createFlowEditor({ flow, intric: makeIntric() });
    try {
      const originalSteps = get(editor.state.update).steps;

      editor.setDescription("Updated description");

      const { update, hasUnsavedChanges } = readEditorState(editor);
      expect(update.name).toBe("Original name");
      expect(update.description).toBe("Updated description");
      expect(update.metadata_json).toEqual({ owner: "metadata" });
      expect(update.steps).toBe(originalSteps);
      expect(update.data_retention_days).toBe(14);
      expect(hasUnsavedChanges).toBe(true);

      editor.setDescription("");
      expect(get(editor.state.update).description).toBe("");
    } finally {
      editor.destroy();
    }
  });

  it("sets data retention while preserving zero, null, and neighboring fields", () => {
    const flow = makeFlow({ owner: "metadata" }, { name: "Flow", description: "Description" });
    const editor = createFlowEditor({ flow, intric: makeIntric() });
    try {
      const originalSteps = get(editor.state.update).steps;

      editor.setDataRetentionDays(0);
      expect(get(editor.state.update).data_retention_days).toBe(0);

      editor.setDataRetentionDays(7);
      let update = get(editor.state.update);
      expect(update.data_retention_days).toBe(7);
      expect(update.name).toBe("Flow");
      expect(update.description).toBe("Description");
      expect(update.metadata_json).toEqual({ owner: "metadata" });
      expect(update.steps).toBe(originalSteps);
      expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(true);

      editor.setDataRetentionDays(Number.NaN);
      update = get(editor.state.update);
      expect(update.data_retention_days).toBeNull();

      editor.setDataRetentionDays(null);
      const { update: finalUpdate, hasUnsavedChanges } = readEditorState(editor);
      expect(finalUpdate.data_retention_days).toBeNull();
      expect(hasUnsavedChanges).toBe(false);
    } finally {
      editor.destroy();
    }
  });
});

describe("FlowEditor form field reference rewrites", () => {
  it("rewrites safe bare and namespaced field references to the canonical namespaced token", async () => {
    const flow = makeFlow(null, {
      steps: [
        makeStep(1, {
          input_bindings: {
            question: "Case {{case_id}} and again {{ flow_input.case_id }}"
          } as never
        })
      ]
    });
    const editor = createFlowEditor({ flow, intric: makeIntric() });
    try {
      await editor.rewriteInputFieldVariableReferences("case_id", "kundnamn");

      const [step] = get(editor.state.update).steps ?? [];
      expect(step.input_bindings).toEqual({
        question: "Case {{flow_input.kundnamn}} and again {{flow_input.kundnamn}}"
      });
    } finally {
      editor.destroy();
    }
  });

  it("does not rewrite bare shadowed system variables when renaming a reserved field", async () => {
    const flow = makeFlow(null, {
      steps: [
        makeStep(1, {
          input_bindings: {
            question: "System date {{datum}} and field {{ flow_input.datum }}"
          } as never
        })
      ]
    });
    const editor = createFlowEditor({ flow, intric: makeIntric() });
    try {
      await editor.rewriteInputFieldVariableReferences("datum", "mötesdatum");

      const [step] = get(editor.state.update).steps ?? [];
      expect(step.input_bindings).toEqual({
        question: "System date {{datum}} and field {{flow_input.mötesdatum}}"
      });
    } finally {
      editor.destroy();
    }
  });

  it("leaves references unchanged when the new field name is not usable", async () => {
    const flow = makeFlow(null, {
      steps: [
        makeStep(1, {
          input_bindings: { question: "Case {{flow_input.case_id}}" } as never
        })
      ]
    });
    const editor = createFlowEditor({ flow, intric: makeIntric() });
    try {
      await editor.rewriteInputFieldVariableReferences("case_id", "flow_input");

      const [step] = get(editor.state.update).steps ?? [];
      expect(step.input_bindings).toEqual({
        question: "Case {{flow_input.case_id}}"
      });
    } finally {
      editor.destroy();
    }
  });
});

describe("FlowEditor step mutation commands", () => {
  it("replaces one step while preserving neighbors and step order", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2)] }),
      intric: makeIntric()
    });
    try {
      const currentSteps = get(editor.state.update).steps;
      const firstStep = currentSteps[0];
      const secondStep = currentSteps[1];

      editor.replaceStepAtIndex(1, {
        ...secondStep,
        step_order: 99,
        user_description: "Updated"
      });

      const { update, hasUnsavedChanges } = readEditorState(editor);
      expect(update.steps[0]).toBe(firstStep);
      expect(update.steps[1]).not.toBe(secondStep);
      expect(update.steps[1]?.user_description).toBe("Updated");
      expect(update.steps[1]?.step_order).toBe(2);
      expect(hasUnsavedChanges).toBe(true);
    } finally {
      editor.destroy();
    }
  });

  it("tracks review policy changes in the persisted step diff", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1)] }),
      intric: makeIntric()
    });
    try {
      const [step] = get(editor.state.update).steps;

      editor.replaceStepAtIndex(0, {
        ...step,
        review_policy: { mode: "edit" }
      });

      const currentChanges = get(editor.state.currentChanges);
      expect(currentChanges.diff.steps?.[0]?.review_policy).toEqual({ mode: "edit" });
    } finally {
      editor.destroy();
    }
  });

  it("ignores invalid replace indexes without changing the step array", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2)] }),
      intric: makeIntric()
    });
    try {
      const originalSteps = get(editor.state.update).steps;
      const replacement = makeStep(1, { user_description: "Invalid" });

      for (const index of [-1, 1.5, Number.NaN, originalSteps.length]) {
        editor.replaceStepAtIndex(index, replacement);
        expect(get(editor.state.update).steps).toBe(originalSteps);
      }
      expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(false);
    } finally {
      editor.destroy();
    }
  });

  it("removes a step, renumbers survivors, and selects the next step", async () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2), makeStep(3)] }),
      intric: makeIntric()
    });
    try {
      editor.selectStep("step-2");

      await editor.removeStepAtIndex(1);

      const update = get(editor.state.update);
      expect(update.steps.map((step) => step.id)).toEqual(["step-1", "step-3"]);
      expect(update.steps.map((step) => step.step_order)).toEqual([1, 2]);
      expect(get(editor.state.activeStepId)).toBe("step-3");
      expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(true);
    } finally {
      editor.destroy();
    }
  });

  it("falls back to the previous step when removing the last step", async () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2)] }),
      intric: makeIntric()
    });
    try {
      editor.selectStep("step-2");

      await editor.removeStepAtIndex(1);

      expect(get(editor.state.update).steps.map((step) => step.id)).toEqual(["step-1"]);
      expect(get(editor.state.activeStepId)).toBe("step-1");
    } finally {
      editor.destroy();
    }
  });

  it("clears the active step when removing the only step", async () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1)] }),
      intric: makeIntric()
    });
    try {
      editor.selectStep("step-1");

      await editor.removeStepAtIndex(0);

      expect(get(editor.state.update).steps).toEqual([]);
      expect(get(editor.state.activeStepId)).toBeNull();
    } finally {
      editor.destroy();
    }
  });

  it("ignores invalid remove indexes without changing steps or active step", async () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2)] }),
      intric: makeIntric()
    });
    try {
      editor.selectStep("step-1");
      const originalSteps = get(editor.state.update).steps;

      for (const index of [-1, 1.5, Number.NaN, originalSteps.length]) {
        await editor.removeStepAtIndex(index);
        expect(get(editor.state.update).steps).toBe(originalSteps);
        expect(get(editor.state.activeStepId)).toBe("step-1");
      }
      expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(false);
    } finally {
      editor.destroy();
    }
  });

  it("propagates remap failures without changing the active step", async () => {
    const assistantUpdate = vi.fn(async () => {
      throw new Error("assistant update failed");
    });
    const editor = createFlowEditor({
      flow: makeFlow(null, {
        steps: [
          makeStep(1),
          makeStep(2, {
            input_bindings: { question: "{{step_1.output.text}}" }
          })
        ]
      }),
      intric: makeIntric({
        assistantGet: vi.fn(async () => ({
          prompt: { text: "{{step_1.output.text}}", description: "" }
        })),
        assistantUpdate
      })
    });
    try {
      editor.selectStep("step-2");

      await expect(editor.removeStepAtIndex(0)).rejects.toThrow("assistant update failed");

      expect(assistantUpdate).toHaveBeenCalled();
      expect(get(editor.state.activeStepId)).toBe("step-2");
    } finally {
      editor.destroy();
    }
  });

  it("uses temporary ids as stable keys when reordering unsaved steps", async () => {
    const tempFirst = makeStep(1, { id: "_temp_alpha", assistant_id: "" });
    const tempSecond = makeStep(2, {
      id: "_temp_beta",
      assistant_id: "",
      input_bindings: { question: "{{step_1.output.text}}" }
    });
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [tempFirst, tempSecond] }),
      intric: makeIntric()
    });
    try {
      await editor.applyStepsWithSafeOrderRemap([
        { ...tempSecond, step_order: 1, input_source: "flow_input" },
        { ...tempFirst, step_order: 2, input_source: "previous_step" }
      ]);

      const [firstStep] = get(editor.state.update).steps;
      expect((firstStep.input_bindings as Record<string, unknown>).question).toBe(
        "{{step_2.output.text}}"
      );
    } finally {
      editor.destroy();
    }
  });
});

describe("FlowEditor active step selection commands", () => {
  it("selects a known step id", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2)] }),
      intric: makeIntric()
    });
    try {
      editor.selectStep("step-2");

      expect(get(editor.state.activeStepId)).toBe("step-2");
    } finally {
      editor.destroy();
    }
  });

  it("ignores unknown step ids and preserves the previous active step", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2)] }),
      intric: makeIntric()
    });
    try {
      editor.selectStep("step-1");
      editor.selectStep("missing-step");

      expect(get(editor.state.activeStepId)).toBe("step-1");
    } finally {
      editor.destroy();
    }
  });

  it("selects the first step when none is selected", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2)] }),
      intric: makeIntric()
    });
    try {
      editor.selectFirstStepIfUnselected();

      expect(get(editor.state.activeStepId)).toBe("step-1");
    } finally {
      editor.destroy();
    }
  });

  it("preserves an existing active step when selecting the first step if unselected", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2)] }),
      intric: makeIntric()
    });
    try {
      editor.selectStep("step-2");
      editor.selectFirstStepIfUnselected();

      expect(get(editor.state.activeStepId)).toBe("step-2");
    } finally {
      editor.destroy();
    }
  });

  it("does not select anything when there are no steps", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [] }),
      intric: makeIntric()
    });
    try {
      editor.selectFirstStepIfUnselected();

      expect(get(editor.state.activeStepId)).toBeNull();
    } finally {
      editor.destroy();
    }
  });

  it("lets explicit selection override first-step auto selection", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2)] }),
      intric: makeIntric()
    });
    try {
      editor.selectFirstStepIfUnselected();
      editor.selectStep("step-2");

      expect(get(editor.state.activeStepId)).toBe("step-2");
    } finally {
      editor.destroy();
    }
  });

  it("selects a step from a freshly replaced resource", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1)] }),
      intric: makeIntric()
    });
    try {
      editor.setResource(
        makeFlow(null, {
          steps: [makeStep(1), makeStep(2, { id: "applied-step" })]
        })
      );

      editor.selectStep("applied-step");

      expect(get(editor.state.activeStepId)).toBe("applied-step");
    } finally {
      editor.destroy();
    }
  });
});

describe("FlowEditor HTTP step config validation", () => {
  it("recovers malformed HTTP config and reports missing URLs", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, {
        steps: [
          makeStep(1, {
            output_mode: "http_post",
            output_config: { auth: { mode: "oauth" }, url: 7 }
          }),
          makeStep(2, {
            input_source: "http_get",
            input_config: { auth: { mode: "oauth" }, url: 7 }
          })
        ]
      }),
      intric: makeIntric()
    });
    try {
      const errors = get(editor.state.validationErrors);

      expect(errors.get("flow:step-config:http_missing_url:1")).toEqual(["http_missing_url"]);
      expect(errors.get("flow:step-config:http_missing_url:2")).toEqual(["http_missing_url"]);
    } finally {
      editor.destroy();
    }
  });

  it("reports missing URLs for HTTP steps without persisted auth shape", () => {
    const editor = createFlowEditor({
      flow: makeFlow(null, {
        steps: [
          makeStep(1, {
            output_mode: "http_post",
            output_config: {}
          }),
          makeStep(2, {
            input_source: "http_post",
            input_config: null
          })
        ]
      }),
      intric: makeIntric()
    });
    try {
      const errors = get(editor.state.validationErrors);

      expect(errors.get("flow:step-config:http_missing_url:1")).toEqual(["http_missing_url"]);
      expect(errors.get("flow:step-config:http_missing_url:2")).toEqual(["http_missing_url"]);
    } finally {
      editor.destroy();
    }
  });
});

describe("FlowEditor save flushing", () => {
  it("persists pending flow step bindings before explicit navigation or publish actions continue", async () => {
    const flowUpdate = vi.fn(async ({ flow, update }) => ({
      ...(flow as Flow),
      ...(update as Partial<Flow>)
    }));
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2)] }),
      intric: makeIntric({ flowUpdate })
    });
    try {
      const steps = get(editor.state.update).steps;

      editor.replaceStepAtIndex(1, {
        ...steps[1],
        input_bindings: { question: "Granskade minnesanteckningar:\n{{step_1.output.text}}" }
      });

      await editor.flushFlowSaves();

      expect(flowUpdate).toHaveBeenCalledTimes(1);
      const [{ update }] = flowUpdate.mock.calls[0] as [{ update: { steps?: FlowStep[] } }];
      expect(update.steps?.map((step) => step.id)).toEqual(["step-1", "step-2"]);
      expect(update.steps?.[1]?.input_bindings).toEqual({
        question: "Granskade minnesanteckningar:\n{{step_1.output.text}}"
      });
      expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(false);
    } finally {
      editor.destroy();
    }
  });

  it("does not include steps when saving a name-only change", async () => {
    const flowUpdate = vi.fn(async ({ flow, update }) => ({
      ...(flow as Flow),
      ...(update as Partial<Flow>)
    }));
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1), makeStep(2)] }),
      intric: makeIntric({ flowUpdate })
    });
    try {
      editor.setName("Renamed flow");

      await editor.flushFlowSaves();

      expect(flowUpdate).toHaveBeenCalledTimes(1);
      const [{ update }] = flowUpdate.mock.calls[0] as [{ update: { steps?: FlowStep[] } }];
      expect(update).toEqual({ name: "Renamed flow" });
      expect(update.steps).toBeUndefined();
    } finally {
      editor.destroy();
    }
  });

  it("sends persisted step ids and strips temporary step ids before saving", async () => {
    const flowUpdate = vi.fn(async ({ flow, update }) => ({
      ...(flow as Flow),
      ...(update as Partial<Flow>)
    }));
    const editor = createFlowEditor({
      flow: makeFlow(null, { steps: [makeStep(1)] }),
      intric: makeIntric({ flowUpdate })
    });
    try {
      const persistedStep = get(editor.state.update).steps[0];
      const newStep = makeStep(2, {
        id: "_temp_new",
        assistant_id: "assistant-2",
        input_source: "previous_step"
      });
      editor.state.update.update((resource) => ({
        ...resource,
        steps: [persistedStep, newStep]
      }));

      await editor.flushFlowSaves();

      expect(flowUpdate).toHaveBeenCalledTimes(1);
      const [{ update }] = flowUpdate.mock.calls[0] as [{ update: { steps?: FlowStep[] } }];
      expect(update.steps?.[0]?.id).toBe("step-1");
      expect(update.steps?.[1]).not.toHaveProperty("id");
    } finally {
      editor.destroy();
    }
  });
});

function renderEditorMetadata({
  flow,
  operation
}: {
  flow: Flow;
  operation: "replace-form" | "empty-form" | "wizard";
}): { metadataJson: unknown; hasUnsavedChanges: boolean } {
  const editor = createFlowEditor({ flow, intric: makeIntric() });
  try {
    if (operation === "replace-form") {
      editor.replaceFormSchemaFields([
        { name: " titel ", type: "email", required: true, options: ["ignored"] },
        { name: "val", type: "select", required: false, options: [" A ", ""] }
      ]);
    } else if (operation === "empty-form") {
      editor.replaceFormSchemaFields([]);
    } else {
      editor.setWizardMetadata({ transcription_model: { id: "model-1" } });
      editor.setTranscriptionEnabled(false);
    }

    const update = get(editor.state.update);
    const currentChanges = get(editor.state.currentChanges);
    return {
      metadataJson: update.metadata_json,
      hasUnsavedChanges: currentChanges.hasUnsavedChanges
    };
  } finally {
    editor.destroy();
  }
}

function readEditorState(editor: ReturnType<typeof createFlowEditor>): {
  update: Flow;
  hasUnsavedChanges: boolean;
} {
  return {
    update: get(editor.state.update),
    hasUnsavedChanges: get(editor.state.currentChanges).hasUnsavedChanges
  };
}
