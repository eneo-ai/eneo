import { describe, expect, it } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";

import { getStepMaterial, ownTextIncludesUpload } from "./flowStepMaterial";

function step(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: "step-2",
    assistant_id: "assistant-2",
    step_order: 2,
    user_description: "Skriv",
    input_source: "previous_step",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    ...overrides
  };
}

describe("flowStepMaterial", () => {
  it("counts only a whole reference to a known upload key as reading the upload", () => {
    expect(ownTextIncludesUpload("Transkript: {{step_input.text}}")).toBe(true);
    expect(ownTextIncludesUpload("Transkript: {{ step_input.text }}")).toBe(true);
    expect(ownTextIncludesUpload("Filer: {{step_input.file_ids}}")).toBe(true);
    expect(ownTextIncludesUpload("Transkript: {{step_input.text")).toBe(false);
    expect(ownTextIncludesUpload("Transkript: {{step_input.typo}}")).toBe(false);
    expect(ownTextIncludesUpload("Namn: {{flow_input.namn}}")).toBe(false);
  });

  it("follows the runtime order: own text, then chosen results, then the source", () => {
    const upload = { runtime_input: { enabled: true, input_format: "document" } };
    expect(getStepMaterial(step({ input_config: upload }), null)).toEqual({ kind: "upload" });
    expect(
      getStepMaterial(
        step({
          input_config: upload,
          input_bindings: { question: "{{step_input.typo}}" } as never
        }),
        null
      )
    ).toMatchObject({ kind: "own_text", withUpload: false });
    expect(
      getStepMaterial(
        step({
          input_bindings: { source_refs: [{ step_ref: "step_1", output: "text" }] } as never
        }),
        null
      )
    ).toEqual({ kind: "sources" });
    expect(getStepMaterial(step(), { step_order: 1, user_description: "Läs" })).toEqual({
      kind: "previous_step",
      stepOrder: 1,
      stepName: "Läs"
    });
  });
});
