import { describe, expect, it } from "vitest";
import {
  getDownstreamKindForOutput,
  getEdgePayloadKind,
  getRecommendedDisplayedInputType,
  getRuntimeFileOriginKind,
  getSourceHintKind,
  getStepSummaryModel,
  sortSelectableInputTypeOptionsForDisplay
} from "./flowStepPresentation";

describe("getSourceHintKind", () => {
  it("explains json output as dual text + structured input", () => {
    expect(getSourceHintKind({ inputSource: "previous_step", previousOutputType: "json" })).toBe(
      "previous_step_json"
    );
  });

  it("explains rendered documents as text-only for chaining", () => {
    expect(getSourceHintKind({ inputSource: "previous_step", previousOutputType: "pdf" })).toBe(
      "previous_step_document_text"
    );
    expect(getSourceHintKind({ inputSource: "previous_step", previousOutputType: "docx" })).toBe(
      "previous_step_document_text"
    );
  });

  it("treats all_previous_steps as tagged text aggregation", () => {
    expect(
      getSourceHintKind({ inputSource: "all_previous_steps", previousOutputType: "json" })
    ).toBe("all_previous_steps");
  });
});

describe("sortSelectableInputTypeOptionsForDisplay", () => {
  it("promotes json ahead of text when the previous step outputs json", () => {
    const ordered = sortSelectableInputTypeOptionsForDisplay({
      inputSource: "previous_step",
      previousOutputType: "json",
      options: [
        { value: "text", disabled: false, legacyInvalid: false },
        { value: "json", disabled: false, legacyInvalid: false },
        { value: "any", disabled: false, legacyInvalid: false }
      ]
    });

    expect(ordered.map((option) => option.value)).toEqual(["json", "text", "any"]);
  });

  it("keeps legacy invalid options pinned first", () => {
    const ordered = sortSelectableInputTypeOptionsForDisplay({
      inputSource: "previous_step",
      previousOutputType: "json",
      options: [
        { value: "file", disabled: false, legacyInvalid: true },
        { value: "text", disabled: false, legacyInvalid: false },
        { value: "json", disabled: false, legacyInvalid: false }
      ]
    });

    expect(ordered.map((option) => option.value)).toEqual(["file", "json", "text"]);
  });
});

describe("getRecommendedDisplayedInputType", () => {
  it("defaults to json for json-producing previous steps", () => {
    const value = getRecommendedDisplayedInputType({
      inputSource: "previous_step",
      previousOutputType: "json",
      options: [
        { value: "text", disabled: false, legacyInvalid: false },
        { value: "json", disabled: false, legacyInvalid: false }
      ]
    });

    expect(value).toBe("json");
  });
});

describe("getDownstreamKindForOutput", () => {
  it("keeps pdf/docx on the text channel", () => {
    expect(getDownstreamKindForOutput("pdf")).toBe("text");
    expect(getDownstreamKindForOutput("docx")).toBe("text");
  });

  it("shows json as both text and structured downstream", () => {
    expect(getDownstreamKindForOutput("json")).toBe("text_and_structured");
  });
});

describe("getEdgePayloadKind", () => {
  it("labels json-to-json edges as structured", () => {
    expect(
      getEdgePayloadKind({
        edgeKind: "previous_step",
        sourceStep: {
          step_order: 1,
          input_source: "flow_input",
          input_type: "text",
          output_type: "json",
          output_mode: "pass_through",
          user_description: "Extract"
        },
        targetStep: {
          step_order: 2,
          input_source: "previous_step",
          input_type: "json",
          output_type: "text",
          output_mode: "pass_through",
          user_description: "Use structured"
        }
      })
    ).toBe("structured");
  });

  it("labels rendered-document chains as text", () => {
    expect(
      getEdgePayloadKind({
        edgeKind: "previous_step",
        sourceStep: {
          step_order: 1,
          input_source: "flow_input",
          input_type: "text",
          output_type: "pdf",
          output_mode: "pass_through",
          user_description: "Render PDF"
        },
        targetStep: {
          step_order: 2,
          input_source: "previous_step",
          input_type: "text",
          output_type: "text",
          output_mode: "pass_through",
          user_description: "Continue"
        }
      })
    ).toBe("text");
  });

  it("hides labels for output edges", () => {
    expect(
      getEdgePayloadKind({
        edgeKind: "flow_output",
        sourceStep: undefined,
        targetStep: null
      })
    ).toBe("none");
  });
});

describe("getRuntimeFileOriginKind", () => {
  it("keeps runtime uploads attached to flow input only", () => {
    expect(getRuntimeFileOriginKind({ needsFileUpload: true, hasFlowInputStep: true })).toBe(
      "flow_input_runtime"
    );
  });

  it("flags http-only flows as having no runtime upload entry point", () => {
    expect(getRuntimeFileOriginKind({ needsFileUpload: false, hasFlowInputStep: false })).toBe(
      "no_runtime_upload"
    );
  });
});

describe("getStepSummaryModel", () => {
  it("summarizes source, output, downstream channel, and context badges", () => {
    const summary = getStepSummaryModel({
      step: {
        step_order: 2,
        input_source: "previous_step",
        input_type: "json",
        output_type: "pdf",
        output_mode: "pass_through",
        user_description: "Render"
      },
      previousStep: {
        step_order: 1,
        input_source: "flow_input",
        input_type: "text",
        output_type: "json",
        output_mode: "pass_through",
        user_description: "Extract"
      },
      hasInputTemplateOverride: true,
      hasKnowledge: true,
      hasAttachments: false
    });

    expect(summary).toMatchObject({
      sourceKind: "previous_step_json",
      sourceStepOrder: 1,
      inputFormat: "json",
      outputFormat: "pdf",
      downstreamKind: "text",
      usesInputTemplate: true,
      hasKnowledge: true,
      hasAttachments: false
    });
  });
});
