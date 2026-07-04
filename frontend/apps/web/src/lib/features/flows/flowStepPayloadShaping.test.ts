import { describe, it, expect } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import {
  stripTemporaryStepId,
  isValidStepIndex,
  getStableStepKey,
  buildBlankStep
} from "./flowStepPayloadShaping";

function makeStep(overrides: Partial<FlowStep>): FlowStep {
  return { id: "s1", assistant_id: "a1", step_order: 1, ...overrides } as FlowStep;
}

describe("stripTemporaryStepId", () => {
  it("removes a temporary id", () => {
    expect(stripTemporaryStepId(makeStep({ id: "_temp_abc" })).id).toBeUndefined();
  });

  it("returns real-id and no-id steps unchanged (same reference)", () => {
    const real = makeStep({ id: "real-1" });
    expect(stripTemporaryStepId(real)).toBe(real);
    const none = makeStep({ id: undefined });
    expect(stripTemporaryStepId(none)).toBe(none);
  });
});

describe("isValidStepIndex", () => {
  const steps = [makeStep({}), makeStep({}), makeStep({})];

  it("accepts in-range integer indices", () => {
    expect(isValidStepIndex(0, steps)).toBe(true);
    expect(isValidStepIndex(2, steps)).toBe(true);
  });

  it("rejects out-of-range, negative and non-integer indices", () => {
    expect(isValidStepIndex(3, steps)).toBe(false);
    expect(isValidStepIndex(-1, steps)).toBe(false);
    expect(isValidStepIndex(1.5, steps)).toBe(false);
  });
});

describe("getStableStepKey", () => {
  it("prefers id, then assistant_id, then index", () => {
    expect(getStableStepKey(makeStep({ id: "s7" }), 3)).toBe("id:s7");
    expect(getStableStepKey(makeStep({ id: undefined, assistant_id: "a7" }), 3)).toBe(
      "assistant:a7"
    );
    expect(getStableStepKey(makeStep({ id: undefined, assistant_id: undefined }), 3)).toBe(
      "index:3"
    );
  });
});

describe("buildBlankStep", () => {
  it("makes a first step a flow_input text step", () => {
    expect(
      buildBlankStep({ tempId: "_temp_1", stepOrder: 1, name: "Steg 1", isFirst: true })
    ).toMatchObject({
      id: "_temp_1",
      assistant_id: "",
      step_order: 1,
      user_description: "Steg 1",
      input_source: "flow_input",
      input_type: "text",
      output_mode: "pass_through",
      output_type: "text",
      mcp_policy: "inherit"
    });
  });

  it("derives a non-first step's input from the previous output type", () => {
    const step = buildBlankStep({
      tempId: "_temp_2",
      stepOrder: 2,
      name: "Steg 2",
      isFirst: false,
      prevStepOutputType: "json"
    });
    expect(step.input_source).toBe("previous_step");
    expect(step.input_type).toBe("json");
  });

  it("applies seed output overrides", () => {
    const step = buildBlankStep({
      tempId: "_temp_3",
      stepOrder: 3,
      name: "Doc",
      isFirst: false,
      prevStepOutputType: "text",
      outputType: "docx"
    });
    expect(step.output_mode).toBe("pass_through");
    expect(step.output_type).toBe("docx");
  });
});
