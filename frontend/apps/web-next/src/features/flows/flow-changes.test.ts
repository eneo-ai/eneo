import { describe, expect, it } from "vitest";
import { describeChanges, diffFlowSteps, hasChanges } from "./flow-changes";
import { makeFlow, makeStep } from "./flow-fixtures";

const t = (key: string, values: Record<string, string | number> = {}) =>
  `${key}(${Object.values(values).join(",")})`;

const before = makeFlow({
  steps: [
    makeStep(1, { user_description: "Extrahera" }),
    makeStep(2, { user_description: "Hämta register" }),
    makeStep(3, { user_description: "Bedömning" })
  ]
});

/** Bedömning moved up to second, Hämta register gone, Granska svaret new. */
const after = makeFlow({
  steps: [
    before.steps[0]!,
    { ...before.steps[2]!, step_order: 2 },
    makeStep(3, { id: "step-4", user_description: "Granska svaret" })
  ]
});

describe("diffFlowSteps", () => {
  it("tells an added, a changed, a moved and a removed step apart", () => {
    const changes = diffFlowSteps(before, after);
    expect([...changes.steps]).toEqual([
      ["step-3", "moved"],
      ["step-4", "added"]
    ]);
    expect(changes.removed.map((step) => step.id)).toEqual(["step-2"]);

    const renamed = makeFlow({
      steps: [
        makeStep(1, { user_description: "Extrahera" }),
        makeStep(2, { user_description: "Hämta register" }),
        makeStep(3, { user_description: "Bedöm ärendet" })
      ]
    });
    expect([...diffFlowSteps(before, renamed).steps]).toEqual([["step-3", "changed"]]);
  });

  it("finds nothing when the steps are as they were", () => {
    expect(hasChanges(diffFlowSteps(before, before))).toBe(false);
  });
});

describe("describeChanges", () => {
  it("says what the chat did, in flow order, removed steps last", () => {
    expect(describeChanges(diffFlowSteps(before, after), after, t)).toBe(
      "flows_chat_changed_moved(flows_step_label(2,Bedömning)) " +
        "flows_chat_changed_added(flows_step_label(3,Granska svaret)) " +
        "flows_chat_changed_removed(flows_step_label(2,Hämta register))"
    );
    expect(describeChanges(diffFlowSteps(before, before), before, t)).toBeNull();
  });
});
