import { describe, it, expect } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import { computeStepOrderRemap } from "./flowStepOrderRemap";

function makeStep(overrides: Record<string, unknown>): FlowStep {
  return { assistant_id: "a", step_order: 1, ...overrides } as FlowStep;
}

function question(step: FlowStep): string {
  return (step.input_bindings as { question?: string } | null)?.question ?? "";
}

describe("computeStepOrderRemap", () => {
  it("maps surviving steps by stable identity when order changes", () => {
    const prev = [makeStep({ id: "A", step_order: 1 }), makeStep({ id: "B", step_order: 2 })];
    const next = [makeStep({ id: "B", step_order: 1 }), makeStep({ id: "A", step_order: 2 })];
    const result = computeStepOrderRemap(prev, next);
    expect(result.remapByOldOrder.get(1)).toBe(2); // A: 1 -> 2
    expect(result.remapByOldOrder.get(2)).toBe(1); // B: 2 -> 1
    expect(result.deletedOrders.size).toBe(0);
  });

  it("detects a removed step's order as deleted", () => {
    const prev = [makeStep({ id: "A", step_order: 1 }), makeStep({ id: "B", step_order: 2 })];
    const next = [makeStep({ id: "A", step_order: 1 })];
    const result = computeStepOrderRemap(prev, next);
    expect([...result.deletedOrders]).toEqual([2]);
  });

  it("rewrites a binding token that points at a moved step order", () => {
    const prev = [
      makeStep({ id: "A", step_order: 1 }),
      makeStep({ id: "C", step_order: 2, input_bindings: { question: "use {{step_1.output}}" } })
    ];
    const next = [
      makeStep({ id: "A", step_order: 2 }),
      makeStep({ id: "C", step_order: 1, input_bindings: { question: "use {{step_1.output}}" } })
    ];
    const result = computeStepOrderRemap(prev, next);
    const c = result.rewrittenSteps.find((s) => s.id === "C")!;
    expect(question(c)).toBe("use {{step_2.output}}");
  });

  it("marks a binding token that points at a deleted step order", () => {
    const prev = [
      makeStep({ id: "A", step_order: 1 }),
      makeStep({ id: "B", step_order: 2 }),
      makeStep({ id: "C", step_order: 3, input_bindings: { question: "{{step_2.output}}" } })
    ];
    const next = [
      makeStep({ id: "A", step_order: 1 }),
      makeStep({ id: "C", step_order: 2, input_bindings: { question: "{{step_2.output}}" } })
    ];
    const result = computeStepOrderRemap(prev, next);
    expect([...result.deletedOrders]).toEqual([2]);
    expect([...result.impactedDeletedBindingOrders]).toEqual([2]);
    const c = result.rewrittenSteps.find((s) => s.id === "C")!;
    expect(question(c)).toContain("step_2_deleted");
  });

  it("rewrites typed source_refs that point at moved step orders", () => {
    const prev = [
      makeStep({ id: "A", step_order: 1 }),
      makeStep({
        id: "C",
        step_order: 2,
        input_bindings: {
          source_refs: [
            {
              step_ref: "step_1",
              output: "structured",
              field_path: "facts.date",
              label: "Document date"
            }
          ]
        }
      })
    ];
    const next = [
      makeStep({ id: "A", step_order: 2 }),
      makeStep({
        id: "C",
        step_order: 1,
        input_bindings: {
          source_refs: [
            {
              step_ref: "step_1",
              output: "structured",
              field_path: "facts.date",
              label: "Document date"
            }
          ]
        }
      })
    ];

    const result = computeStepOrderRemap(prev, next);
    const c = result.rewrittenSteps.find((s) => s.id === "C")!;
    expect((c.input_bindings as { source_refs: Array<{ step_ref: string }> }).source_refs).toEqual([
      {
        step_ref: "step_2",
        output: "structured",
        field_path: "facts.date",
        label: "Document date"
      }
    ]);
  });

  it("marks typed source_refs that point at a deleted step order", () => {
    const prev = [
      makeStep({ id: "A", step_order: 1 }),
      makeStep({ id: "B", step_order: 2 }),
      makeStep({
        id: "C",
        step_order: 3,
        input_bindings: { source_refs: [{ step_ref: "step_2", output: "text" }] }
      })
    ];
    const next = [
      makeStep({ id: "A", step_order: 1 }),
      makeStep({
        id: "C",
        step_order: 2,
        input_bindings: { source_refs: [{ step_ref: "step_2", output: "text" }] }
      })
    ];

    const result = computeStepOrderRemap(prev, next);
    const c = result.rewrittenSteps.find((s) => s.id === "C")!;
    expect([...result.impactedDeletedBindingOrders]).toEqual([2]);
    expect((c.input_bindings as { source_refs: Array<{ step_ref: string }> }).source_refs).toEqual([
      { step_ref: "step_2_deleted", output: "text" }
    ]);
  });

  it("leaves steps without binding questions untouched", () => {
    const prev = [makeStep({ id: "A", step_order: 1 })];
    const next = [makeStep({ id: "A", step_order: 1 })];
    const result = computeStepOrderRemap(prev, next);
    expect(result.impactedDeletedBindingOrders.size).toBe(0);
    expect(result.rewrittenSteps).toHaveLength(1);
  });
});
