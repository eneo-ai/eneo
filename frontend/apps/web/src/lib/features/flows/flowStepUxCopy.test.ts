import { describe, expect, it } from "vitest";

import { getFlowStepUxCopy } from "./flowStepUxCopy";

describe("flowStepUxCopy", () => {
  it("keeps variable examples in the placeholders in both languages", () => {
    expect(getFlowStepUxCopy({ locale: "sv" }).inputTemplatePlaceholder).toBe(
      "t.ex.\nÄrende: {{ärendenummer}}\nSammanfattning: {{Sammanfatta ärendet}}"
    );
    expect(getFlowStepUxCopy({ locale: "en" }).inputTemplatePlaceholder).toBe(
      "e.g.\nCase: {{case_number}}\nSummary: {{Summarize the case}}"
    );
    expect(getFlowStepUxCopy({ locale: "en" }).instructionsTitle).toBe("Instruction for the AI");
  });
});
