import { describe, expect, it } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";

import {
  applyInputSourceChange,
  applyInputTypeChange,
  applyOutputModeChange,
  applyOutputTypeChange
} from "./flowStepTransitionPolicy";
import type { FlowRuntimeInputConfigValue } from "./flowRuntimeInputConfig";
import { getTemplateFillOutputConfig } from "./templateFillConfig";

function makeRuntimeInputConfig(
  overrides: Partial<FlowRuntimeInputConfigValue> = {}
): FlowRuntimeInputConfigValue {
  return {
    enabled: false,
    required: false,
    input_format: "document",
    accepted_mimetypes_override: [],
    max_files: 1,
    label: "",
    description: "",
    ...overrides
  };
}

function makeStep(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: "step-1",
    assistant_id: "assistant-1",
    step_order: 1,
    user_description: "Step",
    input_source: "flow_input",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    ...overrides
  } as FlowStep;
}

describe("flow step transition policy", () => {
  it("seeds HTTP defaults when the source becomes http_get", () => {
    const result = applyInputSourceChange({
      step: makeStep({
        input_source: "flow_input",
        input_type: "audio",
        input_config: null
      }),
      nextSource: "http_get",
      previousOutputType: undefined,
      runtimeInputConfig: makeRuntimeInputConfig(),
      isAdvancedMode: false
    });

    expect(result.step.input_source).toBe("http_get");
    expect(result.step.input_type).toBe("audio");
    expect(result.inputTypeAdjusted).toBe(false);
    expect(result.step.input_config).toMatchObject({
      auth: { mode: "none" },
      body: { mode: "none" },
      custom_headers: [],
      response_format: "text",
      timeout_seconds: 30,
      url: ""
    });
  });

  it("normalizes HTTP config fields while preserving unrelated input config", () => {
    const result = applyInputSourceChange({
      step: makeStep({
        input_source: "flow_input",
        input_type: "text",
        input_config: {
          url: "https://api.example.com/input",
          auth: { mode: "oauth", token: "ignored" },
          timeout_seconds: "fast",
          body: { mode: "xml", template: 5 },
          custom_headers: "not-an-array",
          response_format: "xml",
          runtime_input: { enabled: true },
          headers: { "X-Legacy": "kept" }
        }
      }),
      nextSource: "http_get",
      previousOutputType: undefined,
      runtimeInputConfig: makeRuntimeInputConfig(),
      isAdvancedMode: false
    });

    expect(result.step.input_config).toEqual({
      url: "https://api.example.com/input",
      auth: { mode: "none" },
      timeout_seconds: 30,
      body: { mode: "none" },
      custom_headers: [],
      response_format: "text",
      runtime_input: { enabled: true },
      headers: { "X-Legacy": "kept" }
    });
  });

  it("preserves valid HTTP config fields during input-source transitions", () => {
    const result = applyInputSourceChange({
      step: makeStep({
        input_source: "flow_input",
        input_type: "text",
        input_config: {
          url: "https://api.example.com/input",
          auth: { mode: "bearer_token", token: "token-1" },
          timeout_seconds: 45,
          body: { mode: "json_template", template: '{"case":"{{flow_input.case_id}}"}' },
          custom_headers: [{ name: "X-Trace", value: "abc", secret: false }],
          response_format: "json",
          runtime_input: { enabled: true }
        }
      }),
      nextSource: "http_get",
      previousOutputType: undefined,
      runtimeInputConfig: makeRuntimeInputConfig(),
      isAdvancedMode: false
    });

    expect(result.step.input_config).toEqual({
      url: "https://api.example.com/input",
      auth: { mode: "bearer_token", token: "token-1" },
      timeout_seconds: 45,
      body: { mode: "json_template", template: '{"case":"{{flow_input.case_id}}"}' },
      custom_headers: [{ name: "X-Trace", value: "abc", secret: false }],
      response_format: "json",
      runtime_input: { enabled: true }
    });
  });

  it("forces audio steps onto flow_input and transcribe_only output", () => {
    const result = applyInputTypeChange({
      step: makeStep({
        input_source: "previous_step",
        input_type: "text",
        output_mode: "pass_through",
        output_type: "json"
      }),
      nextType: "audio",
      runtimeInputConfig: makeRuntimeInputConfig()
    });

    expect(result.step.input_type).toBe("audio");
    expect(result.step.input_source).toBe("flow_input");
    expect(result.step.output_mode).toBe("transcribe_only");
    expect(result.step.output_type).toBe("text");
    expect(result.inputSourceAdjusted).toBe(true);
  });

  it("builds a template_fill step with docx output and a draft template config", () => {
    const result = applyOutputModeChange({
      step: makeStep({
        output_mode: "pass_through",
        output_type: "text"
      }),
      nextMode: "template_fill",
      runtimeInputConfig: makeRuntimeInputConfig(),
      templateFillConfig: getTemplateFillOutputConfig(makeStep())
    });

    expect(result.output_type).toBe("docx");
    expect(result.output_mode).toBe("template_fill");
    expect(result.output_contract).toBeNull();
    expect(getTemplateFillOutputConfig(result).bindings).toEqual({});
  });

  it("drops template_fill mode when the user changes output type away from docx", () => {
    const result = applyOutputTypeChange({
      step: makeStep({
        output_mode: "template_fill",
        output_type: "docx",
        output_config: { citation_mode: "inline_inref_sidecar" }
      }),
      nextType: "json"
    });

    expect(result.output_type).toBe("json");
    expect(result.output_mode).toBe("pass_through");
    expect(result.output_config).toBeNull();
  });

  it("clears citation mode when switching to transcribe_only", () => {
    const result = applyOutputModeChange({
      step: makeStep({
        output_mode: "pass_through",
        output_type: "text",
        output_config: { citation_mode: "inline_inref_sidecar" }
      }),
      nextMode: "transcribe_only",
      runtimeInputConfig: makeRuntimeInputConfig(),
      templateFillConfig: getTemplateFillOutputConfig(makeStep())
    });

    expect(result.output_mode).toBe("transcribe_only");
    expect(result.output_config).toBeNull();
  });

  it("clears review policy when switching to outbound output delivery", () => {
    const result = applyOutputModeChange({
      step: makeStep({
        output_mode: "pass_through",
        review_policy: { mode: "edit" }
      }),
      nextMode: "http_post",
      runtimeInputConfig: makeRuntimeInputConfig(),
      templateFillConfig: getTemplateFillOutputConfig(makeStep())
    });

    expect(result.output_mode).toBe("http_post");
    expect(result.review_policy).toBeNull();
  });
});
