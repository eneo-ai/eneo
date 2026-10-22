import { describe, expect, it } from "vitest";
import { readHttpConfig, readLongMaterial, readRuntimeInput } from "./step-configs";
import {
  applyInputSourceChange,
  applyInputTypeChange,
  applyOutputModeChange,
  applyOutputTypeChange,
  chainIssue,
  inputSourceOptions,
  inputTypeOptions,
  outputModeIssue,
  outputModeOptions
} from "./step-rules";
import { stepConfigOf, type StepConfig } from "./step-types";
import { makeStep } from "./testing/fixtures";

const later = (overrides: Partial<StepConfig> = {}): StepConfig => ({
  ...stepConfigOf(makeStep({ step_order: 2, input_source: "previous_step" })),
  ...overrides
});

describe("what a step can read", () => {
  it("offers the flow's input only to step 1 and earlier steps only after it", () => {
    expect(inputSourceOptions(1, "flow_input").map((option) => option.value)).toEqual([
      "flow_input",
      "http_get",
      "tool"
    ]);
    expect(inputSourceOptions(2, "previous_step").map((option) => option.value)).toEqual([
      "previous_step",
      "all_previous_steps",
      "http_get",
      "tool"
    ]);
  });

  it("lists a stored source that no longer fits as invalid instead of hiding it", () => {
    expect(inputSourceOptions(2, "flow_input")[0]).toEqual({ value: "flow_input", invalid: true });
    expect(chainIssue(later({ input_source: "flow_input" }), 2, "text")).toBe(
      "flow_input_not_first"
    );
  });

  it("offers the types the previous step's answer can be read as", () => {
    expect(inputTypeOptions(later(), "docx").map((option) => option.value)).toEqual([
      "text",
      "any"
    ]);
    expect(chainIssue(later({ input_type: "json" }), 2, "pdf")).toBe("incompatible_previous");
    expect(chainIssue(later({ input_type: "json" }), 2, "text")).toBeNull();
  });
});

describe("changing one setting keeps the step valid", () => {
  it("turns audio into a transcription step that takes uploads", () => {
    const step = applyInputTypeChange(stepConfigOf(makeStep()), "audio");
    expect(step).toMatchObject({
      input_source: "flow_input",
      output_mode: "transcribe_only",
      output_type: "text"
    });
    expect(readRuntimeInput(step.input_config)).toMatchObject({
      enabled: true,
      required: true,
      inputFormat: "audio"
    });
  });

  it("keeps a customised upload's settings when it is turned off", () => {
    const document = applyInputTypeChange(stepConfigOf(makeStep()), "document");
    const labelled = {
      ...document,
      input_config: {
        runtime_input: { ...(document.input_config?.runtime_input as object), label: "Ansökan" }
      }
    };
    const toTool = applyInputSourceChange(labelled, "tool", null);
    expect(toTool.input_type).toBe("text");
    expect(toTool.input_config?.runtime_input).toMatchObject({ enabled: false, label: "Ansökan" });
  });

  it("fetching over HTTP starts an authored config, keeps other input settings and drops an underlag", () => {
    const step = applyInputSourceChange(
      later({ input_bindings: { question: "Hej" }, input_config: { future: 1 } }),
      "http_get",
      "text"
    );
    expect(step.input_bindings).toBeNull();
    expect(step.input_config).toMatchObject({ future: 1, auth: { mode: "none" }, url: "" });
    expect(readHttpConfig(step.input_config, "input").response_format).toBe("text");
  });

  it("drops citations and the retrieval policy for a mode without a model, and nothing else", () => {
    const step = later({
      output_config: {
        citation_mode: "inline_inref_sidecar",
        retrieval_policy: { version: 1, mode: "fail_closed" },
        future: true
      }
    });
    expect(applyOutputModeChange(step, "compose_text").output_config).toEqual({ future: true });
  });

  it("makes a speaker mapping always reviewed and review impossible before outbound delivery", () => {
    expect(applyOutputModeChange(later(), "speaker_mapping").review_policy).toEqual({
      mode: "edit"
    });
    const reviewed = later({ review_policy: { mode: "view", expires_after_seconds: 3600 } });
    expect(applyOutputModeChange(reviewed, "http_post").review_policy).toBeNull();
  });

  it("turns a text step that delivers a document into a document step without AI", () => {
    expect(applyOutputTypeChange(later(), "pdf")).toMatchObject({
      output_mode: "render_verbatim",
      output_type: "pdf"
    });
  });
});

describe("long material follows the mode", () => {
  it("ends when the step no longer has a model answer, and stays for HTTP delivery", () => {
    const step = later({ input_config: { long_material: { mode: "digest" } } });
    expect(readLongMaterial(applyOutputModeChange(step, "compose_text").input_config)).toBe(false);
    expect(readLongMaterial(applyOutputModeChange(step, "http_post").input_config)).toBe(true);
  });
});

describe("output modes", () => {
  it("offers HTTP delivery only to the last step and says why it does not fit elsewhere", () => {
    const step = later();
    expect(outputModeOptions(step, false).map((option) => option.value)).not.toContain("http_post");
    expect(outputModeIssue({ ...step, output_mode: "http_post" }, false)).toBe(
      "http_post_must_be_last"
    );
  });

  it("marks a stored mode that no longer fits the types as invalid", () => {
    const step = later({ output_mode: "copy_input", input_type: "text", output_type: "json" });
    expect(outputModeOptions(step, true).find((option) => option.value === "copy_input")).toEqual({
      value: "copy_input",
      invalid: true
    });
  });
});
