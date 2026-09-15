import { describe, it, expect } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import {
  computeStepConfigValidationIssues,
  hasDeletedStepReferences
} from "./flowStepConfigValidation";

function makeStep(overrides: Record<string, unknown>): FlowStep {
  return {
    id: "s1",
    assistant_id: "a1",
    step_order: 1,
    input_source: "flow_input",
    output_mode: "pass_through",
    ...overrides
  } as FlowStep;
}

const PREFIX = "flow:step-config:";

describe("computeStepConfigValidationIssues", () => {
  it("flags a template_fill step with no template asset", () => {
    const issues = computeStepConfigValidationIssues(
      [makeStep({ output_mode: "template_fill", step_order: 2 })],
      PREFIX
    );
    expect([...issues.keys()]).toContain(`${PREFIX}template_fill_no_template:2`);
  });

  it("flags template placeholders without a mapping and mappings without a placeholder", () => {
    const step = (bindings: Record<string, unknown>) =>
      makeStep({
        output_mode: "template_fill",
        output_type: "docx",
        step_order: 3,
        output_config: {
          template_asset_id: "asset-1",
          placeholders: ["namn", "datum"],
          bindings
        }
      });
    const missing = computeStepConfigValidationIssues(
      [step({ namn: "{{ flow_input.namn }}" })],
      PREFIX
    );
    expect([...missing.keys()]).toEqual([`${PREFIX}template_fill_missing_mappings:3`]);

    const orphaned = computeStepConfigValidationIssues(
      [step({ namn: "x", datum: "y", gammal: "z" })],
      PREFIX
    );
    expect([...orphaned.keys()]).toEqual([`${PREFIX}template_fill_orphaned_mappings:3`]);

    // An explicit empty mapping is a deliberate choice, not a missing one.
    const complete = computeStepConfigValidationIssues([step({ namn: "x", datum: "" })], PREFIX);
    expect([...complete.keys()]).toEqual([]);
  });

  it("does not judge mappings without a placeholder inventory (Builder-made drafts)", () => {
    // The Builder materializes the asset and bindings without a placeholder
    // list; publication inspects the DOCX itself. Unknown is not invalid.
    const issues = computeStepConfigValidationIssues(
      [
        makeStep({
          output_mode: "template_fill",
          output_type: "docx",
          step_order: 2,
          output_config: {
            template_asset_id: "asset-1",
            bindings: { namn: "{{ flow_input.namn }}" }
          }
        })
      ],
      PREFIX
    );
    expect([...issues.keys()]).toEqual([]);
  });

  it("passes a plain step with no config requirements", () => {
    expect(computeStepConfigValidationIssues([makeStep({})], PREFIX).size).toBe(0);
  });

  it("flags an http_post output step with no url", () => {
    const issues = computeStepConfigValidationIssues(
      [makeStep({ output_mode: "http_post", step_order: 3 })],
      PREFIX
    );
    expect([...issues.keys()]).toContain(`${PREFIX}http_missing_url:3`);
  });

  it("flags an http_get input step with no url", () => {
    const issues = computeStepConfigValidationIssues(
      [makeStep({ input_source: "http_get", step_order: 4 })],
      PREFIX
    );
    expect([...issues.keys()]).toContain(`${PREFIX}http_missing_url:4`);
  });

  it("blocks publishing an incompatible output mode without rewriting the step", () => {
    const issues = computeStepConfigValidationIssues(
      [
        makeStep({
          input_type: "text",
          output_type: "pdf",
          output_mode: "pass_through",
          step_order: 5
        })
      ],
      PREFIX
    );

    expect([...issues.keys()]).toContain(`${PREFIX}output_mode_incompatible:5`);
  });

  it("accepts a compatible render_verbatim document step", () => {
    const issues = computeStepConfigValidationIssues(
      [
        makeStep({
          input_type: "text",
          output_type: "pdf",
          output_mode: "render_verbatim"
        })
      ],
      PREFIX
    );

    expect([...issues.keys()]).not.toContain(`${PREFIX}output_mode_incompatible:1`);
  });
});

describe("hasDeletedStepReferences", () => {
  const noCache = new Map<string, string>();

  it("detects a deleted-step token in input_bindings.question", () => {
    const step = makeStep({ input_bindings: { question: "See {{step_2_deleted}} here" } });
    expect(hasDeletedStepReferences([step], noCache)).toBe(true);
  });

  it("detects a deleted typed source ref in input_bindings.source_refs", () => {
    const step = makeStep({
      input_bindings: { source_refs: [{ step_ref: "step_2_deleted", output: "text" }] }
    });
    expect(hasDeletedStepReferences([step], noCache)).toBe(true);
  });

  it("detects a deleted-step token in the cached prompt text", () => {
    const step = makeStep({ assistant_id: "a9" });
    expect(
      hasDeletedStepReferences([step], new Map([["a9", "uses {{step_3_deleted_output}}"]]))
    ).toBe(true);
  });

  it("returns false when nothing references a deleted step", () => {
    const step = makeStep({
      input_bindings: { question: "clean {{step_1_output}}" },
      assistant_id: "a9"
    });
    expect(hasDeletedStepReferences([step], new Map([["a9", "clean prompt text"]]))).toBe(false);
  });
});

describe("speaker_mapping config validation", () => {
  it("flags a mapping step without a participants field", () => {
    const step = {
      id: "s2",
      assistant_id: "a",
      step_order: 2,
      user_description: "Namnge talare",
      input_source: "previous_step",
      input_type: "text",
      output_mode: "speaker_mapping",
      output_type: "json",
      input_bindings: null,
      input_contract: null,
      output_contract: null,
      input_config: null,
      output_config: { speaker_mapping: { participants_field: null } },
      review_policy: { mode: "edit" }
    } as unknown as import("@eneo/eneo-js").FlowStep;
    const issues = computeStepConfigValidationIssues([step], "p:");
    expect(issues.get("p:speaker_mapping_no_participants_field:2")).toEqual([
      "speaker_mapping_no_participants_field"
    ]);
    const ok = computeStepConfigValidationIssues(
      [{ ...step, output_config: { speaker_mapping: { participants_field: "deltagare" } } }],
      "p:"
    );
    expect(ok.has("p:speaker_mapping_no_participants_field:2")).toBe(false);
    // The conversation itself is the name source when inference is on.
    const inferring = computeStepConfigValidationIssues(
      [
        {
          ...step,
          output_config: { speaker_mapping: { participants_field: null, infer_names: true } }
        }
      ],
      "p:"
    );
    expect(inferring.has("p:speaker_mapping_no_participants_field:2")).toBe(false);
  });
});
