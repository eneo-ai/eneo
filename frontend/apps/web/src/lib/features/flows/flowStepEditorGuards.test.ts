import { describe, expect, test } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import {
  needsTranscribeOnlyOutputModeReset,
  needsTranscribeOnlyOutputTypeCoercion,
  shouldAutoClearLegacyTemplate
} from "./flowStepEditorGuards";

function makeStep(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: "step-1",
    step_order: 1,
    user_description: "Test step",
    input_source: "flow_input",
    input_type: "text",
    output_type: "text",
    output_mode: "pass_through",
    mcp_policy: "inherit",
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    input_bindings: null,
    output_classification_override: null,
    assistant_id: null,
    ...overrides
  } as FlowStep;
}

// ---------------------------------------------------------------------------
// shouldAutoClearLegacyTemplate
// ---------------------------------------------------------------------------

describe("shouldAutoClearLegacyTemplate", () => {
  const base = {
    stepId: "step-1",
    isPublished: false,
    hasInputTemplateOverride: true,
    instructionText: "Summarize the document",
    inputTemplateText: "Summarize the document",
    alreadyAutoCleared: false
  };

  test("clears when template mirrors the instruction on an unpublished step", () => {
    expect(shouldAutoClearLegacyTemplate(base)).toBe(true);
  });

  test("ignores surrounding whitespace when comparing", () => {
    expect(
      shouldAutoClearLegacyTemplate({
        ...base,
        instructionText: "  Summarize the document  ",
        inputTemplateText: "Summarize the document\n"
      })
    ).toBe(true);
  });

  test("does not clear when the template differs from the instruction", () => {
    expect(shouldAutoClearLegacyTemplate({ ...base, inputTemplateText: "Something else" })).toBe(
      false
    );
  });

  test("does not clear published steps", () => {
    expect(shouldAutoClearLegacyTemplate({ ...base, isPublished: true })).toBe(false);
  });

  test("does not clear without a step id", () => {
    expect(shouldAutoClearLegacyTemplate({ ...base, stepId: null })).toBe(false);
    expect(shouldAutoClearLegacyTemplate({ ...base, stepId: undefined })).toBe(false);
  });

  test("does not clear when there is no input template override", () => {
    expect(shouldAutoClearLegacyTemplate({ ...base, hasInputTemplateOverride: false })).toBe(false);
  });

  test("does not clear when the instruction is empty", () => {
    expect(
      shouldAutoClearLegacyTemplate({ ...base, instructionText: "   ", inputTemplateText: "   " })
    ).toBe(false);
  });

  test("does not clear when it has already been auto-cleared", () => {
    expect(shouldAutoClearLegacyTemplate({ ...base, alreadyAutoCleared: true })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// needsTranscribeOnlyOutputTypeCoercion
// ---------------------------------------------------------------------------

describe("needsTranscribeOnlyOutputTypeCoercion", () => {
  test("coerces a stale non-text output type on a transcribe_only step", () => {
    expect(
      needsTranscribeOnlyOutputTypeCoercion(
        makeStep({ output_mode: "transcribe_only", output_type: "json" })
      )
    ).toBe(true);
  });

  test("no coercion when output type is already text", () => {
    expect(
      needsTranscribeOnlyOutputTypeCoercion(
        makeStep({ output_mode: "transcribe_only", output_type: "text" })
      )
    ).toBe(false);
  });

  test("no coercion for non-transcribe_only modes", () => {
    expect(
      needsTranscribeOnlyOutputTypeCoercion(
        makeStep({ output_mode: "pass_through", output_type: "json" })
      )
    ).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// needsTranscribeOnlyOutputModeReset
// ---------------------------------------------------------------------------

describe("needsTranscribeOnlyOutputModeReset", () => {
  test("resets when a transcribe_only step no longer takes audio input", () => {
    expect(
      needsTranscribeOnlyOutputModeReset(
        makeStep({ input_type: "text", output_mode: "transcribe_only" })
      )
    ).toBe(true);
  });

  test("keeps transcribe_only when the input is still audio", () => {
    expect(
      needsTranscribeOnlyOutputModeReset(
        makeStep({ input_type: "audio", output_mode: "transcribe_only" })
      )
    ).toBe(false);
  });

  test("no reset for non-transcribe_only modes", () => {
    expect(
      needsTranscribeOnlyOutputModeReset(
        makeStep({ input_type: "text", output_mode: "pass_through" })
      )
    ).toBe(false);
  });
});
