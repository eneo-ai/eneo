import { describe, expect, it } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import {
  OUTPUT_MODES,
  getAvailableOutputModes,
  getAvailableOutputTypes,
  getFlowStepValidationIssues,
  getOutputModeCompatibilityIssue,
  getSelectableInputTypeOptions,
  getValidInputSources,
  getValidInputTypes,
  hasOutboundDeliveryOutputMode,
  mapOutputToInputType
} from "./flowStepTypes";

function outputStep(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    ...overrides
  } as FlowStep;
}

describe("output mode catalog", () => {
  it("stays exhaustive with the generated backend output-mode union", () => {
    expect(OUTPUT_MODES.map((mode) => mode.value)).toEqual([
      "pass_through",
      "compose_text",
      "transcribe_only",
      "template_fill",
      "render_verbatim",
      "http_post"
    ]);
  });
});

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

  it("allows zero-flow_input source flows via HTTP GET", () => {
    expect(getValidInputTypes("http_get")).toEqual(["text", "json", "any"]);
  });

  it("limits all_previous_steps to text and any", () => {
    expect(getValidInputTypes("all_previous_steps")).toEqual(["text", "any"]);
  });
});

describe("getValidInputSources", () => {
  it("offers HTTP GET but never the removed HTTP POST input source", () => {
    expect(getValidInputSources({ steps: [], stepOrder: 1 })).toEqual(["flow_input", "http_get"]);
    expect(getValidInputSources({ steps: [], stepOrder: 2 })).toEqual([
      "previous_step",
      "all_previous_steps",
      "http_get"
    ]);
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

  it("restricts template_fill steps while preserving an invalid saved output type", () => {
    const options = getAvailableOutputTypes(outputStep({ output_mode: "template_fill" }));
    expect(options.map((type) => type.value)).toEqual(["text", "docx"]);
    expect(options[0]).toMatchObject({ value: "text", legacyInvalid: true });
  });

  it("offers only document formats for render_verbatim while preserving an invalid saved value", () => {
    const options = getAvailableOutputTypes(
      outputStep({ output_mode: "render_verbatim", output_type: "text" })
    );

    expect(options.map((type) => type.value)).toEqual(["text", "pdf", "docx"]);
    expect(options[0]).toMatchObject({ value: "text", legacyInvalid: true });
  });

  it("restricts compose_text steps to text output", () => {
    const values = getAvailableOutputTypes(
      outputStep({ output_mode: "compose_text", output_type: "text" })
    ).map((type) => type.value);

    expect(values).toEqual(["text"]);
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

  it("offers deterministic text and document creation for text input", () => {
    const values = getAvailableOutputModes({
      step: outputStep({ input_type: "text", output_type: "text" }),
      isAdvancedMode: false
    }).map((mode) => mode.value);

    expect(values).toContain("compose_text");
    expect(values).toContain("render_verbatim");
  });

  it("does not offer deterministic text or document creation for JSON input", () => {
    const values = getAvailableOutputModes({
      step: outputStep({ input_type: "json", output_type: "json" }),
      isAdvancedMode: true
    }).map((mode) => mode.value);

    expect(values).not.toContain("compose_text");
    expect(values).not.toContain("render_verbatim");
  });

  it("offers deterministic document rendering for text-to-document steps", () => {
    const options = getAvailableOutputModes({
      step: outputStep({
        input_type: "text",
        output_type: "pdf",
        output_mode: "pass_through"
      }),
      isAdvancedMode: false
    });

    expect(options.map((mode) => mode.value)).toContain("render_verbatim");
    expect(options.find((mode) => mode.value === "pass_through")).toMatchObject({
      legacyInvalid: true
    });
  });

  it("keeps an incompatible saved mode visible so the user can repair it", () => {
    const options = getAvailableOutputModes({
      step: outputStep({
        input_type: "json",
        output_type: "pdf",
        output_mode: "render_verbatim"
      }),
      isAdvancedMode: false
    });

    expect(options.find((mode) => mode.value === "render_verbatim")).toMatchObject({
      legacyInvalid: true
    });
  });

  it("keeps HTTP delivery out of Simple unless the step already uses it", () => {
    expect(
      getAvailableOutputModes({ step: outputStep(), isAdvancedMode: false }).map(
        (mode) => mode.value
      )
    ).not.toContain("http_post");
    expect(
      getAvailableOutputModes({
        step: outputStep({ output_mode: "http_post" }),
        isAdvancedMode: false
      }).map((mode) => mode.value)
    ).toContain("http_post");
  });
});

describe("getOutputModeCompatibilityIssue", () => {
  it("matches the backend constraints for deterministic modes", () => {
    expect(
      getOutputModeCompatibilityIssue(
        outputStep({ input_type: "text", output_type: "pdf", output_mode: "render_verbatim" })
      )
    ).toBeNull();
    expect(
      getOutputModeCompatibilityIssue(
        outputStep({ input_type: "json", output_type: "pdf", output_mode: "render_verbatim" })
      )
    ).toBe("render_verbatim_requires_text_document");
    expect(
      getOutputModeCompatibilityIssue(
        outputStep({ input_type: "text", output_type: "json", output_mode: "compose_text" })
      )
    ).toBe("compose_text_requires_text");
  });

  it("rejects text-to-document pass-through so the repair path is explicit", () => {
    expect(
      getOutputModeCompatibilityIssue(
        outputStep({ input_type: "text", output_type: "docx", output_mode: "pass_through" })
      )
    ).toBe("text_document_requires_render_verbatim");
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

  it("allows zero-flow_input HTTP GET-only flows", () => {
    const issues = getFlowStepValidationIssues([
      { step_order: 1, input_source: "http_get", input_type: "text", output_type: "text" },
      { step_order: 2, input_source: "http_get", input_type: "text", output_type: "text" }
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
