import { describe, it, expect } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import {
  getDefaultOpenStepChapter,
  getStepAiWorkKind,
  getStepChapterStateKey
} from "./flowStepEditorPresentation";
import { outputModeUsesCompletionModel } from "./flowStepTypes";

function step(partial: Partial<FlowStep>): FlowStep {
  return {
    input_source: "previous_step",
    input_type: "text",
    output_type: "text",
    output_mode: "pass_through",
    step_order: 2,
    ...partial
  } as unknown as FlowStep;
}

describe("getStepAiWorkKind", () => {
  it("classifies transcribe-only steps as transcribe", () => {
    expect(
      getStepAiWorkKind(step({ output_mode: "transcribe_only", input_type: "audio" }), {
        instructionPresent: null
      })
    ).toBe("transcribe");
  });

  it("classifies HTTP output steps as http", () => {
    expect(
      getStepAiWorkKind(step({ output_mode: "http_post" }), { instructionPresent: true })
    ).toBe("http");
  });

  it("classifies HTTP GET input steps as http", () => {
    expect(
      getStepAiWorkKind(step({ input_source: "http_get" }), { instructionPresent: null })
    ).toBe("http");
  });

  it("classifies template-fill steps as template", () => {
    expect(
      getStepAiWorkKind(step({ output_mode: "template_fill" }), { instructionPresent: false })
    ).toBe("template");
  });

  it("keeps deterministic output modes outside the AI instruction contract", () => {
    expect(outputModeUsesCompletionModel("compose_text")).toBe(false);
    expect(outputModeUsesCompletionModel("render_verbatim")).toBe(false);
    expect(outputModeUsesCompletionModel("pass_through")).toBe(true);
    expect(outputModeUsesCompletionModel("http_post")).toBe(true);
    expect(
      getStepAiWorkKind(step({ output_mode: "render_verbatim", output_type: "pdf" }), {
        instructionPresent: false
      })
    ).toBe("document");
  });

  it("marks an LLM step with a known-empty instruction as missing", () => {
    expect(getStepAiWorkKind(step({}), { instructionPresent: false })).toBe("missing");
  });

  it("marks an LLM step with an instruction as process", () => {
    expect(getStepAiWorkKind(step({}), { instructionPresent: true })).toBe("process");
  });

  it("classifies docx/pdf output steps as document", () => {
    expect(getStepAiWorkKind(step({ output_type: "pdf" }), { instructionPresent: true })).toBe(
      "document"
    );
    expect(getStepAiWorkKind(step({ output_type: "docx" }), { instructionPresent: true })).toBe(
      "document"
    );
  });

  it("prefers the missing warning over the document kind when the instruction is empty", () => {
    expect(getStepAiWorkKind(step({ output_type: "docx" }), { instructionPresent: false })).toBe(
      "missing"
    );
  });

  it("never reports missing while the instruction is still unknown (loading)", () => {
    expect(getStepAiWorkKind(step({}), { instructionPresent: null })).toBe("process");
  });
});

describe("getDefaultOpenStepChapter", () => {
  it("opens the task for a normal AI step", () => {
    expect(getDefaultOpenStepChapter({ step: step({}) })).toBe("task");
  });

  it("opens material for transcription steps", () => {
    expect(
      getDefaultOpenStepChapter({
        step: step({ input_type: "audio", output_mode: "transcribe_only" })
      })
    ).toBe("input");
  });

  it("opens result for deterministic document and template steps", () => {
    expect(getDefaultOpenStepChapter({ step: step({ output_mode: "render_verbatim" }) })).toBe(
      "result"
    );
    expect(getDefaultOpenStepChapter({ step: step({ output_mode: "template_fill" }) })).toBe(
      "result"
    );
  });

  it("opens the first section that needs repair", () => {
    expect(getDefaultOpenStepChapter({ step: step({}), hasInputError: true })).toBe("input");
    expect(getDefaultOpenStepChapter({ step: step({}), hasOutputError: true })).toBe("result");
  });
});

describe("getStepChapterStateKey", () => {
  it("keeps one key across the temp-to-real id swap of a step being created", () => {
    const temp = getStepChapterStateKey({
      activeStep: { id: "_temp_new", step_order: 2 },
      newStepOpenIntent: { token: "_temp_new", stepId: "_temp_new" }
    });
    const afterSave = getStepChapterStateKey({
      activeStep: { id: "step-real-2", step_order: 2 },
      newStepOpenIntent: { token: "_temp_new", stepId: "step-real-2" }
    });

    // The chapters the user opened while the first save was in flight belong
    // to the same step afterwards.
    expect(afterSave).toBe(temp);
  });

  it("keys every other step by its id", () => {
    expect(
      getStepChapterStateKey({
        activeStep: { id: "step-1", step_order: 1 },
        newStepOpenIntent: null
      })
    ).toBe("step-1");
    expect(
      getStepChapterStateKey({
        activeStep: { id: "step-1", step_order: 1 },
        newStepOpenIntent: { token: "_temp_new", stepId: "step-real-2" }
      })
    ).toBe("step-1");
  });

  it("has a key when no step is open", () => {
    expect(getStepChapterStateKey({ activeStep: null, newStepOpenIntent: null })).toBe("no-step");
  });
});
