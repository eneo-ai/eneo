import { describe, expect, it } from "vitest";

import {
  resolveAIBuilderApplyNavigation,
  resolveApplyFocusedStepId
} from "./flowAIBuilderApplyNavigation";

describe("flowAIBuilderApplyNavigation", () => {
  it("routes applied plans with steps back to builder stage 4 and keeps the requested focus", () => {
    expect(
      resolveAIBuilderApplyNavigation({
        stepCount: 3,
        requestedFocusStepIndex: 2
      })
    ).toEqual({
      activeTab: "builder",
      builderStage: 4,
      focusStepIndex: 2
    });
  });

  it("falls back to the first step when there is no valid focus mapping", () => {
    expect(
      resolveAIBuilderApplyNavigation({
        stepCount: 2,
        requestedFocusStepIndex: 9
      })
    ).toEqual({
      activeTab: "builder",
      builderStage: 4,
      focusStepIndex: 0
    });
  });

  it("returns stage 1 and no focused step when the flow has no steps", () => {
    expect(
      resolveAIBuilderApplyNavigation({
        stepCount: 0,
        requestedFocusStepIndex: null
      })
    ).toEqual({
      activeTab: "builder",
      builderStage: 1,
      focusStepIndex: null
    });
  });

  it("resolves the focused step id with a safe first-step fallback", () => {
    const steps = [{ id: "step-1" }, { id: "step-2" }];

    expect(resolveApplyFocusedStepId(steps, 1)).toBe("step-2");
    expect(resolveApplyFocusedStepId(steps, null)).toBe("step-1");
    expect(resolveApplyFocusedStepId([], 0)).toBeNull();
  });
});
