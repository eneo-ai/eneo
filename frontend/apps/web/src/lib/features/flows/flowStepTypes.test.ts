import { describe, expect, it } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import {
  getAvailableOutputModes,
  getAvailableOutputTypes,
  getFlowStepValidationIssues,
  getSelectableInputTypeOptions,
  getValidInputTypes,
  hasOutboundDeliveryOutputMode,
  mapOutputToInputType
} from "./flowStepTypes";

function outputStep(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    input_type: "text",
    output_mode: "pass_through",
    ...overrides
  } as FlowStep;
}

describe("mapOutputToInputType", () => {
  it("maps rendered document outputs back to text for chaining", () => {
    expect(mapOutputToInputType("pdf")).toBe("text");
    expect(mapOutputToInputType("docx")).toBe("text");
  });
});

describe("hasOutboundDeliveryOutputMode", () => {
  it("centralizes which output modes deliver outside the run result payload", () => {
    expect(hasOutboundDeliveryOutputMode("http_post")).toBe(true);
    expect(hasOutboundDeliveryOutputMode("pass_through")).toBe(false);
    expect(hasOutboundDeliveryOutputMode("template_fill")).toBe(false);
    expect(hasOutboundDeliveryOutputMode("transcribe_only")).toBe(false);
  });
});

describe("getValidInputTypes", () => {
  it("returns the canonical matrix for previous_step sources", () => {
    expect(getValidInputTypes("previous_step", "text")).toEqual(["text", "json", "any"]);
    expect(getValidInputTypes("previous_step", "json")).toEqual(["text", "json", "any"]);
    expect(getValidInputTypes("previous_step", "pdf")).toEqual(["text", "any"]);
    expect(getValidInputTypes("previous_step", "docx")).toEqual(["text", "any"]);
  });

  it("allows zero-flow_input source flows via HTTP", () => {
    expect(getValidInputTypes("http_get")).toEqual(["text", "json", "any"]);
    expect(getValidInputTypes("http_post")).toEqual(["text", "json", "any"]);
  });

  it("limits all_previous_steps to text and any", () => {
    expect(getValidInputTypes("all_previous_steps")).toEqual(["text", "any"]);
  });
});

describe("getSelectableInputTypeOptions", () => {
  it("hides advanced-only types in user mode", () => {
    const options = getSelectableInputTypeOptions({
      inputSource: "flow_input",
      previousOutputType: undefined,
      currentInputType: "text",
      isAdvancedMode: false
    });

    expect(options.map((option) => option.value)).toEqual(["text", "json", "document", "audio"]);
  });

  it("shows disabled image and advanced-only types in advanced mode", () => {
    const options = getSelectableInputTypeOptions({
      inputSource: "flow_input",
      previousOutputType: undefined,
      currentInputType: "text",
      isAdvancedMode: true
    });

    expect(options.map((option) => option.value)).toEqual([
      "text",
      "json",
      "document",
      "file",
      "image",
      "audio",
      "any"
    ]);
    expect(options.find((option) => option.value === "image")?.disabled).toBe(true);
  });

  it("preserves an invalid saved value as legacy instead of auto-correcting", () => {
    const options = getSelectableInputTypeOptions({
      inputSource: "previous_step",
      previousOutputType: "pdf",
      currentInputType: "json",
      isAdvancedMode: false
    });

    expect(options.map((option) => option.value)).toEqual(["json", "text"]);
    expect(options[0]).toMatchObject({ value: "json", legacyInvalid: true });
  });

  it("keeps a valid advanced-only current value visible in user mode", () => {
    const options = getSelectableInputTypeOptions({
      inputSource: "previous_step",
      previousOutputType: "json",
      currentInputType: "any",
      isAdvancedMode: false
    });

    expect(options.map((option) => option.value)).toEqual(["text", "json", "any"]);
    expect(options.find((option) => option.value === "any")?.legacyInvalid).toBe(false);
  });
});

describe("getAvailableOutputTypes", () => {
  it("restricts transcribe_only steps to text output", () => {
    const values = getAvailableOutputTypes(outputStep({ output_mode: "transcribe_only" })).map(
      (type) => type.value
    );
    expect(values).toEqual(["text"]);
  });

  it("restricts template_fill steps to docx output", () => {
    const values = getAvailableOutputTypes(outputStep({ output_mode: "template_fill" })).map(
      (type) => type.value
    );
    expect(values).toEqual(["docx"]);
  });

  it("offers every output type for a plain pass_through step", () => {
    const values = getAvailableOutputTypes(outputStep()).map((type) => type.value);
    expect(values).toEqual(["text", "json", "pdf", "docx"]);
  });

  it("offers every output type when there is no active step", () => {
    const values = getAvailableOutputTypes(null).map((type) => type.value);
    expect(values).toEqual(["text", "json", "pdf", "docx"]);
  });
});

describe("getAvailableOutputModes", () => {
  it("hides transcribe_only unless the input is audio", () => {
    const values = getAvailableOutputModes({
      step: outputStep({ input_type: "text" }),
      isAdvancedMode: true
    }).map((mode) => mode.value);
    expect(values).not.toContain("transcribe_only");
  });

  it("exposes transcribe_only for audio input", () => {
    const values = getAvailableOutputModes({
      step: outputStep({ input_type: "audio" }),
      isAdvancedMode: true
    }).map((mode) => mode.value);
    expect(values).toContain("transcribe_only");
  });

  it("hides template_fill in user mode", () => {
    const values = getAvailableOutputModes({
      step: outputStep({ input_type: "text" }),
      isAdvancedMode: false
    }).map((mode) => mode.value);
    expect(values).not.toContain("template_fill");
  });

  it("keeps template_fill visible in user mode when the step already uses it", () => {
    const values = getAvailableOutputModes({
      step: outputStep({ input_type: "text", output_mode: "template_fill" }),
      isAdvancedMode: false
    }).map((mode) => mode.value);
    expect(values).toContain("template_fill");
  });

  it("shows template_fill in advanced mode", () => {
    const values = getAvailableOutputModes({
      step: outputStep({ input_type: "text" }),
      isAdvancedMode: true
    }).map((mode) => mode.value);
    expect(values).toContain("template_fill");
  });
});

describe("getFlowStepValidationIssues", () => {
  it("rejects duplicate flow_input steps", () => {
    const issues = getFlowStepValidationIssues([
      { step_order: 1, input_source: "flow_input", input_type: "text", output_type: "text" },
      { step_order: 2, input_source: "flow_input", input_type: "text", output_type: "text" }
    ]);

    expect(issues.map((issue) => issue.code)).toContain("typed_io_multiple_flow_input_steps");
  });

  it("allows zero-flow_input HTTP-only flows", () => {
    const issues = getFlowStepValidationIssues([
      { step_order: 1, input_source: "http_get", input_type: "text", output_type: "text" },
      { step_order: 2, input_source: "http_post", input_type: "text", output_type: "text" }
    ]);

    expect(issues).toEqual([]);
  });

  it("flags incompatible legacy previous-step chains", () => {
    const issues = getFlowStepValidationIssues([
      { step_order: 1, input_source: "flow_input", input_type: "text", output_type: "pdf" },
      { step_order: 2, input_source: "previous_step", input_type: "json", output_type: "text" }
    ]);

    expect(issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          code: "typed_io_incompatible_type_chain",
          stepOrder: 2
        })
      ])
    );
  });
});
