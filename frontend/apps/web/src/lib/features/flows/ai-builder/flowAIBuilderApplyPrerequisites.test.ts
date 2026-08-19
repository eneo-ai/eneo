import { describe, expect, it } from "vitest";

import {
  getAIBuilderApplyPrerequisites,
  hasAIBuilderApplyBlocker
} from "./flowAIBuilderApplyPrerequisites";
import type { StepSpec } from "./protocol";

describe("flowAIBuilderApplyPrerequisites", () => {
  it("blocks create plans with flow-input audio when no accessible transcription model exists", () => {
    const prerequisites = getAIBuilderApplyPrerequisites({
      plan: makePlan({ input_source: "flow_input", input_type: "audio" }),
      targetKind: "create",
      transcriptionModels: [{ can_access: false }]
    });

    expect(prerequisites.canApply).toBe(false);
    expect(prerequisites.blockers).toEqual([{ code: "transcription_model_required" }]);
    expect(hasAIBuilderApplyBlocker(prerequisites, "transcription_model_required")).toBe(true);
  });

  it("allows create audio plans when the space has an accessible transcription model", () => {
    const prerequisites = getAIBuilderApplyPrerequisites({
      plan: makePlan({ input_source: "flow_input", input_type: "audio" }),
      targetKind: "create",
      transcriptionModels: [{ can_access: false }, { can_access: true }]
    });

    expect(prerequisites.canApply).toBe(true);
    expect(prerequisites.blockers).toEqual([]);
  });

  it("does not block edit plans because the backend create-only invariant owns this check", () => {
    const prerequisites = getAIBuilderApplyPrerequisites({
      plan: makePlan({ input_source: "flow_input", input_type: "audio" }),
      targetKind: "edit",
      transcriptionModels: []
    });

    expect(prerequisites.canApply).toBe(true);
    expect(prerequisites.blockers).toEqual([]);
  });

  it("does not invent an embedding-model blocker for existing knowledge references", () => {
    const prerequisites = getAIBuilderApplyPrerequisites({
      plan: makePlan({
        assistant_spec: {
          instructions: "Use the selected knowledge.",
          knowledge_refs: ["knowledge_1"],
          model_ref: null
        }
      }),
      targetKind: "create",
      transcriptionModels: []
    });

    expect(prerequisites.canApply).toBe(true);
    expect(prerequisites.blockers).toEqual([]);
  });
});

function makePlan(stepOverrides: Partial<StepSpec> = {}) {
  return {
    proposal: {
      spec: makeSpec(stepOverrides)
    }
  };
}

function makeSpec(stepOverrides: Partial<StepSpec>) {
  return {
    flow_name: "Audio intake",
    flow_description: "Transcribe an uploaded audio file.",
    steps: [makeStep(stepOverrides)],
    form_fields: []
  };
}

function makeStep(overrides: Partial<StepSpec>): StepSpec {
  return {
    plan_step_ref: "step_a",
    existing_step_ref: null,
    name: "Transcribe audio",
    assistant_spec: {
      instructions: "Transcribe the uploaded audio.",
      knowledge_refs: [],
      model_ref: null
    },
    input_source: "flow_input",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    ...overrides
  };
}
