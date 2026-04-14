import { describe, expect, it } from "vitest";

import { shouldHandleFlowRunsReload } from "./flowRunsReload";

describe("shouldHandleFlowRunsReload", () => {
  it("does not reload for the initial zero trigger", () => {
    expect(shouldHandleFlowRunsReload(0, 0)).toBe(false);
  });

  it("reloads when the trigger increments", () => {
    expect(shouldHandleFlowRunsReload(1, 0)).toBe(true);
  });

  it("does not reload again for the same trigger value", () => {
    expect(shouldHandleFlowRunsReload(1, 1)).toBe(false);
  });

  it("does not reload when the trigger moves backwards", () => {
    expect(shouldHandleFlowRunsReload(1, 2)).toBe(false);
  });

  it("reloads again on the next increment", () => {
    expect(shouldHandleFlowRunsReload(3, 2)).toBe(true);
  });
});
