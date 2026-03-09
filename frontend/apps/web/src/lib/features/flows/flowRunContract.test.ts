import { describe, expect, it } from "vitest";

import {
  buildStepInputsPayload,
  getBlockingTemplateReadinessItems,
  normalizeTemplateReadiness
} from "./flowRunContract";

describe("flowRunContract helpers", () => {
  it("builds canonical step_inputs payload from uploaded files", () => {
    expect(
      buildStepInputsPayload({
        "step-1": [{ id: "file-1" }, { id: "file-2" }],
        "step-2": []
      })
    ).toEqual({
      "step-1": { file_ids: ["file-1", "file-2"] }
    });
  });

  it("normalizes template readiness values into a list", () => {
    expect(normalizeTemplateReadiness(null)).toEqual([]);
    expect(
      normalizeTemplateReadiness({
        step_id: "step-1",
        status: "ready"
      })
    ).toHaveLength(1);
  });

  it("marks unavailable and needs_action template states as blocking", () => {
    expect(
      getBlockingTemplateReadinessItems([
        { step_id: "step-1", status: "ready" },
        { step_id: "step-2", status: "unavailable" },
        { step_id: "step-3", status: "needs_action" }
      ])
    ).toEqual([
      { step_id: "step-2", status: "unavailable" },
      { step_id: "step-3", status: "needs_action" }
    ]);
  });
});
