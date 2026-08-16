import { describe, expect, it } from "vitest";

import { getRevisedStepRefs } from "./flowAIBuilderPlanRevisionDiff";
import type { FlowDraftSpecCore, StepSpec } from "./protocol";

function makeStep(overrides: Partial<StepSpec> = {}): StepSpec {
  return {
    plan_step_ref: "step_a",
    existing_step_ref: null,
    name: "Transkribera ljud",
    assistant_spec: {
      instructions: "Transkribera det uppladdade ljudet.",
      knowledge_refs: [],
      model_ref: null
    },
    input_source: "flow_input",
    input_type: "audio",
    output_mode: "transcribe_only",
    output_type: "text",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    ...overrides
  };
}

function makeSpec(steps: StepSpec[]): FlowDraftSpecCore {
  return { flow_name: "Flöde", flow_description: "", steps, form_fields: [] };
}

describe("getRevisedStepRefs", () => {
  it("marks nothing for the first plan in a session", () => {
    expect(getRevisedStepRefs(null, makeSpec([makeStep()]))).toEqual(new Set());
  });

  it("marks nothing when the replacement plan is identical", () => {
    const before = makeSpec([makeStep(), makeStep({ plan_step_ref: "step_b", name: "Skriv PDF" })]);
    const after = makeSpec([makeStep(), makeStep({ plan_step_ref: "step_b", name: "Skriv PDF" })]);

    expect(getRevisedStepRefs(before, after)).toEqual(new Set());
  });

  it("marks only the step whose content changed", () => {
    const before = makeSpec([makeStep(), makeStep({ plan_step_ref: "step_b", name: "Skriv PDF" })]);
    const after = makeSpec([
      makeStep(),
      makeStep({
        plan_step_ref: "step_b",
        name: "Skriv PDF",
        assistant_spec: {
          instructions: "Skriv PDF med sammanfattning på första sidan.",
          knowledge_refs: [],
          model_ref: null
        }
      })
    ]);

    expect(getRevisedStepRefs(before, after)).toEqual(new Set(["step_b"]));
  });

  it("survives the positional plan_step_ref renaming an inserted step causes", () => {
    // The backend stamps refs by index, so inserting a step at the top renames
    // every ref below it. Only the genuinely new step may be marked.
    const before = makeSpec([
      makeStep({ plan_step_ref: "step_a", name: "Transkribera ljud" }),
      makeStep({ plan_step_ref: "step_b", name: "Skriv PDF" })
    ]);
    const after = makeSpec([
      makeStep({ plan_step_ref: "step_a", name: "Läs in bilagan" }),
      makeStep({ plan_step_ref: "step_b", name: "Transkribera ljud" }),
      makeStep({ plan_step_ref: "step_c", name: "Skriv PDF" })
    ]);

    expect(getRevisedStepRefs(before, after)).toEqual(new Set(["step_a"]));
  });

  it("marks a renamed step, because the user sees it as changed", () => {
    const before = makeSpec([makeStep({ name: "Transkribera ljud" })]);
    const after = makeSpec([makeStep({ name: "Transkribera nämndmötet" })]);

    expect(getRevisedStepRefs(before, after)).toEqual(new Set(["step_a"]));
  });

  it("ignores key order differences from serialization", () => {
    const before = makeSpec([makeStep()]);
    const reordered = JSON.parse(
      JSON.stringify(makeStep(), ["output_type", "name", "plan_step_ref"])
    ) as StepSpec;
    const after = makeSpec([{ ...reordered, ...makeStep() }]);

    expect(getRevisedStepRefs(before, after)).toEqual(new Set());
  });
});
