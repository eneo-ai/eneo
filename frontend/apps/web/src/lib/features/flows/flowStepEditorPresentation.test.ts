import { describe, it, expect } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import { getStepAiWorkKind } from "./flowStepEditorPresentation";

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
