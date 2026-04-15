import { describe, expect, it } from "vitest";

import {
  getFirstChangedStepIndex,
  getRemovedStepChanges,
  getStepChangeKind
} from "./flowAIBuilderPlanDiff";
import type { FlowEditDiff, StepSpec } from "./protocol";

function makeStep(overrides: Partial<StepSpec> = {}): StepSpec {
  return {
    plan_step_ref: overrides.plan_step_ref ?? "step_a",
    existing_step_ref: overrides.existing_step_ref ?? null,
    name: overrides.name ?? "Step",
    assistant_spec: overrides.assistant_spec ?? {
      instructions: "Do work",
      model_ref: null,
      knowledge_refs: []
    },
    input_source: overrides.input_source ?? "previous_step",
    input_type: overrides.input_type ?? "text",
    output_mode: overrides.output_mode ?? "pass_through",
    output_type: overrides.output_type ?? "text",
    input_bindings: overrides.input_bindings ?? null,
    input_contract: overrides.input_contract ?? null,
    output_contract: overrides.output_contract ?? null,
    input_config: overrides.input_config ?? null,
    output_config: overrides.output_config ?? null
  };
}

function makeEditDiff(stepChanges: FlowEditDiff["step_changes"]): FlowEditDiff {
  return {
    step_changes: stepChanges,
    net_steps_added: stepChanges.filter((change) => change.kind === "added").length,
    net_steps_removed: stepChanges.filter((change) => change.kind === "removed").length,
    flow_property_changes: {}
  };
}

describe("flowAIBuilderPlanDiff", () => {
  it("uses edit_diff to distinguish unchanged existing steps from modified ones", () => {
    const unchanged = makeStep({
      plan_step_ref: "step_a",
      existing_step_ref: "existing_step_1",
      name: "First"
    });
    const modified = makeStep({
      plan_step_ref: "step_b",
      existing_step_ref: "existing_step_2",
      name: "Second"
    });
    const editDiff = makeEditDiff([
      { kind: "unchanged", step_name: "First", step_ref: "existing_step_1", details: null },
      {
        kind: "modified",
        step_name: "Second",
        step_ref: "existing_step_2",
        details: "output_type → pdf"
      }
    ]);

    expect(getStepChangeKind(unchanged, editDiff)).toBe("unchanged");
    expect(getStepChangeKind(modified, editDiff)).toBe("modified");
    expect(getFirstChangedStepIndex([unchanged, modified], editDiff)).toBe(1);
  });

  it("keeps added steps actionable and returns removed steps separately", () => {
    const added = makeStep({ plan_step_ref: "step_c", existing_step_ref: null, name: "New" });
    const editDiff = makeEditDiff([
      { kind: "removed", step_name: "Old", step_ref: "existing_step_1", details: null }
    ]);

    expect(getStepChangeKind(added, editDiff)).toBe("added");
    expect(getRemovedStepChanges(editDiff)).toEqual([
      { kind: "removed", step_name: "Old", step_ref: "existing_step_1", details: null }
    ]);
    expect(getFirstChangedStepIndex([added], editDiff)).toBe(0);
  });
});
