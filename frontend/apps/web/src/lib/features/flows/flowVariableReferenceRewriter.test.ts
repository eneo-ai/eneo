import { describe, it, expect } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import { rewriteStepBindings } from "./flowVariableReferenceRewriter";

function makeStep(overrides: Record<string, unknown>): FlowStep {
  return { id: "s1", assistant_id: "a1", step_order: 1, ...overrides } as FlowStep;
}

const upper = (q: string) => q.toUpperCase();

describe("rewriteStepBindings", () => {
  it("rewrites a step's input_bindings.question", () => {
    const [result] = rewriteStepBindings(
      [makeStep({ input_bindings: { question: "hello" } })],
      upper
    );
    expect((result.input_bindings as { question: string }).question).toBe("HELLO");
  });

  it("preserves other binding keys", () => {
    const [result] = rewriteStepBindings(
      [makeStep({ input_bindings: { question: "hi", other: 7 } })],
      upper
    );
    expect(result.input_bindings).toEqual({ question: "HI", other: 7 });
  });

  it("returns the same reference for a step with no question", () => {
    const step = makeStep({ input_bindings: { other: 1 } });
    expect(rewriteStepBindings([step], upper)[0]).toBe(step);
  });

  it("returns the same reference when the rewrite is a no-op", () => {
    const step = makeStep({ input_bindings: { question: "ALREADY" } });
    expect(rewriteStepBindings([step], upper)[0]).toBe(step);
  });

  it("returns the same reference for null input_bindings", () => {
    const step = makeStep({ input_bindings: null });
    expect(rewriteStepBindings([step], upper)[0]).toBe(step);
  });

  it("skips steps for which shouldSkip returns true", () => {
    const steps = [
      makeStep({ step_order: 1, input_bindings: { question: "a" } }),
      makeStep({ step_order: 2, input_bindings: { question: "b" } })
    ];
    const result = rewriteStepBindings(steps, upper, (s) => s.step_order <= 1);
    expect(result[0]).toBe(steps[0]);
    expect((result[1].input_bindings as { question: string }).question).toBe("B");
  });
});
