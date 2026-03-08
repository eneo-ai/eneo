import { describe, expect, it } from "vitest";

import { shouldShowTemplateBodyTextHint } from "./templateFillAuthoringHints";

describe("templateFillAuthoringHints", () => {
  const baseStep = {
    step_order: 1,
    output_mode: "pass_through"
  } as never;

  it("shows the hint when a later template_fill step exists", () => {
    expect(
      shouldShowTemplateBodyTextHint({
        steps: [
          baseStep,
          {
            step_order: 2,
            output_mode: "template_fill"
          } as never
        ],
        activeStep: baseStep,
        isAdvancedMode: true,
        isTemplateFill: false,
        isTranscribeOnly: false
      })
    ).toBe(true);
  });

  it("hides the hint outside advanced mode", () => {
    expect(
      shouldShowTemplateBodyTextHint({
        steps: [
          baseStep,
          {
            step_order: 2,
            output_mode: "template_fill"
          } as never
        ],
        activeStep: baseStep,
        isAdvancedMode: false,
        isTemplateFill: false,
        isTranscribeOnly: false
      })
    ).toBe(false);
  });

  it("hides the hint for template_fill and transcription steps themselves", () => {
    expect(
      shouldShowTemplateBodyTextHint({
        steps: [
          {
            step_order: 1,
            output_mode: "template_fill"
          } as never
        ],
        activeStep: {
          step_order: 1,
          output_mode: "template_fill"
        } as never,
        isAdvancedMode: true,
        isTemplateFill: true,
        isTranscribeOnly: false
      })
    ).toBe(false);

    expect(
      shouldShowTemplateBodyTextHint({
        steps: [
          {
            step_order: 1,
            output_mode: "transcribe_only"
          } as never,
          {
            step_order: 2,
            output_mode: "template_fill"
          } as never
        ],
        activeStep: {
          step_order: 1,
          output_mode: "transcribe_only"
        } as never,
        isAdvancedMode: true,
        isTemplateFill: false,
        isTranscribeOnly: true
      })
    ).toBe(false);
  });
});
