import { describe, expect, it } from "vitest";
import {
  longMaterialEligibility,
  readHttpConfig,
  readLongMaterial,
  readRuntimeInput,
  supportsCitations
} from "./step-configs";
import {
  applyHttpOutputChange,
  applyInputSourceChange,
  applyInputTypeChange,
  applyOutputModeChange,
  applyOutputTypeChange,
  boundFormField,
  chainIssue,
  formFieldFitsArgument,
  inputSourceOptions,
  inputTypeOptions,
  outputModeIssue,
  outputModeOptions,
  outputTypeOptions,
  stepUsesModel
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

  it("keeps a document's name when it becomes text, and drops only the file name", () => {
    const document = later({
      input_type: "json",
      output_type: "docx",
      output_config: { deliverable: { label: "Eneo", file_name: "Standup" }, future: true }
    });
    expect(applyOutputTypeChange(document, "text").output_config).toEqual({
      deliverable: { label: "Eneo" },
      future: true
    });
  });

  it("drops the deliverable when the step can no longer be one, and nothing else", () => {
    const document = later({
      input_type: "json",
      output_type: "docx",
      output_config: { deliverable: { label: "Eneo" }, future: true }
    });
    expect(applyOutputTypeChange(document, "json").output_config).toEqual({ future: true });
    expect(applyOutputModeChange(document, "http_post").output_config).not.toHaveProperty(
      "deliverable"
    );
    expect(applyOutputModeChange(document, "http_post").output_config).toMatchObject({
      future: true
    });
    expect(applyOutputTypeChange(document, "pdf").output_config).toEqual({
      deliverable: { label: "Eneo" },
      future: true
    });
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

describe("a step that sends the run's result", () => {
  /** An outbound step with an AI answer as JSON and everything only a model uses. */
  const outbound = (body: Record<string, unknown>, overrides: Partial<StepConfig> = {}) =>
    later({
      output_mode: "http_post",
      output_type: "json",
      output_contract: { type: "object" },
      output_config: {
        url: "https://receiver.example.org/eneo",
        body,
        citation_mode: "inline_inref_sidecar",
        retrieval_policy: { version: 1, mode: "fail_closed" }
      },
      input_config: { long_material: { mode: "digest" } },
      ...overrides
    });
  const withBody = (step: StepConfig, mode: "auto", url?: string) => {
    const http = readHttpConfig(step.output_config, "output");
    return applyHttpOutputChange(step, { ...http, url: url ?? http.url, body: { mode } });
  };

  it("calls no model: it sends text and offers nothing only a model uses", () => {
    const step = outbound({ mode: "run_result" }, { output_type: "text", output_contract: null });
    expect(stepUsesModel(step)).toBe(false);
    expect(outputTypeOptions(step).map((option) => option.value)).toEqual(["text"]);
    expect(supportsCitations(step)).toBe(false);
    expect(longMaterialEligibility(step)).toBe("output");
  });

  it("drops the contracts and what only a model uses when it sends the run's result again", () => {
    // A step that sent the run's result, set to another mode and back.
    const left = outbound(
      { mode: "run_result" },
      {
        output_mode: "pass_through",
        output_type: "text",
        input_contract: { type: "object" },
        output_contract: { type: "string" }
      }
    );
    const step = applyOutputModeChange(
      { ...left, output_config: { ...left.output_config, auth: { mode: "none" } } },
      "http_post"
    );
    expect(step).toMatchObject({
      output_type: "text",
      input_contract: null,
      output_contract: null
    });
    expect(step.output_config).not.toHaveProperty("citation_mode");
    expect(step.output_config).not.toHaveProperty("retrieval_policy");
  });

  it("leaves an ordinary outbound step as it is when its call changes", () => {
    const step = outbound({ mode: "auto" });
    expect(stepUsesModel(step)).toBe(true);
    const changed = withBody(step, "auto", "https://other.example.org/eneo");
    expect(changed).toMatchObject({ output_type: "json", output_contract: { type: "object" } });
    expect(changed.output_config).toMatchObject({
      url: "https://other.example.org/eneo",
      citation_mode: "inline_inref_sidecar",
      retrieval_policy: { version: 1, mode: "fail_closed" }
    });
    expect(readLongMaterial(changed.input_config)).toBe(true);
    expect(outputTypeOptions(changed).map((option) => option.value)).toContain("json");
  });

  it("reads a body left from an outbound call only while the step sends one", () => {
    const left = outbound({ mode: "run_result" }, { output_mode: "pass_through" });
    expect(stepUsesModel(left)).toBe(true);
    expect(longMaterialEligibility(left)).toBe("eligible");
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

describe("a form field read by a tool argument", () => {
  const flow = {
    metadata_json: {
      form_schema: {
        fields: [
          { name: "deltagare", label: "Deltagare", type: "list" },
          { name: "antal", label: "Antal", type: "number" },
          { name: "namn", label: "Namn", type: "text" }
        ]
      }
    }
  };

  it("finds the field a whole reference reads, and nothing else", () => {
    expect(boundFormField("{{flow_input.deltagare}}", flow)).toMatchObject({
      name: "deltagare",
      type: "list"
    });
    expect(boundFormField("{{ flow_input.antal }}", flow)).toMatchObject({ name: "antal" });
    expect(boundFormField("{{step_1.output.text}}", flow)).toBeNull();
    expect(boundFormField("Hej {{flow_input.namn}}", flow)).toBeNull();
    expect(boundFormField(5, flow)).toBeNull();
  });

  it("fits only the JSON type the run gives the field: text, a number or a list of text", () => {
    const arg = (type: string | null, items: string | null = null) => ({ type, items });
    // A list of text cannot be a list of numbers, nor one value.
    expect(formFieldFitsArgument("list", arg("array", "number"))).toBe(false);
    expect(formFieldFitsArgument("multiselect", arg("string"))).toBe(false);
    expect(formFieldFitsArgument("list", arg("array", "string"))).toBe(true);
    expect(formFieldFitsArgument("list", arg("array"))).toBe(true);
    expect(formFieldFitsArgument("text", arg("number"))).toBe(false);
    expect(formFieldFitsArgument("number", arg("integer"))).toBe(true);
    expect(formFieldFitsArgument("number", arg("string"))).toBe(false);
    expect(formFieldFitsArgument("date", arg("string"))).toBe(true);
    expect(formFieldFitsArgument("select", arg("array", "string"))).toBe(false);
    // An argument the schema does not type takes anything.
    expect(formFieldFitsArgument("list", arg(null))).toBe(true);
  });
});
