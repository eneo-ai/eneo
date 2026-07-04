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
});

describe("hasDeletedStepReferences", () => {
  const noCache = new Map<string, string>();

  it("detects a deleted-step token in input_bindings.question", () => {
    const step = makeStep({ input_bindings: { question: "See {{step_2_deleted}} here" } });
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
