import { describe, expect, test } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import {
  formatAdvancedJson,
  getStepKeyForAdvancedJson,
  getStepAdvancedJsonValue,
  getVisibleAdvancedJsonFields,
  syncDraftsFromStep,
  syncDraftsFromStepValues,
  clearHiddenFieldErrors,
  parseAdvancedJsonField,
  formatAdvancedJsonDraftField,
  getErrorFields,
  ADVANCED_JSON_FIELDS
} from "./advancedJsonDrafts";

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
// formatAdvancedJson
// ---------------------------------------------------------------------------

describe("formatAdvancedJson", () => {
  test("returns empty string for null", () => {
    expect(formatAdvancedJson(null)).toBe("");
  });

  test("returns empty string for undefined", () => {
    expect(formatAdvancedJson(undefined)).toBe("");
  });

  test("formats an object with 2-space indentation", () => {
    expect(formatAdvancedJson({ a: 1 })).toBe('{\n  "a": 1\n}');
  });

  test("formats a string value", () => {
    expect(formatAdvancedJson("hello")).toBe('"hello"');
  });
});

// ---------------------------------------------------------------------------
// getStepKeyForAdvancedJson
// ---------------------------------------------------------------------------

describe("getStepKeyForAdvancedJson", () => {
  test("returns null for null step", () => {
    expect(getStepKeyForAdvancedJson(null)).toBeNull();
  });

  test("returns id:order for a step with id", () => {
    expect(getStepKeyForAdvancedJson(makeStep({ id: "abc", step_order: 3 }))).toBe("abc:3");
  });

  test("uses 'new' for step without id", () => {
    expect(getStepKeyForAdvancedJson(makeStep({ id: undefined, step_order: 1 }))).toBe("new:1");
  });
});

// ---------------------------------------------------------------------------
// getStepAdvancedJsonValue
// ---------------------------------------------------------------------------

describe("getStepAdvancedJsonValue", () => {
  const step = makeStep({
    input_contract: { type: "object" },
    output_contract: { type: "array" },
    input_config: { url: "http://test" },
    output_config: { url: "http://out" }
  });

  test("returns input_contract", () => {
    expect(getStepAdvancedJsonValue(step, "input_contract")).toEqual({ type: "object" });
  });

  test("returns output_contract", () => {
    expect(getStepAdvancedJsonValue(step, "output_contract")).toEqual({ type: "array" });
  });

  test("returns input_config", () => {
    expect(getStepAdvancedJsonValue(step, "input_config")).toEqual({ url: "http://test" });
  });

  test("returns output_config", () => {
    expect(getStepAdvancedJsonValue(step, "output_config")).toEqual({ url: "http://out" });
  });
});

// ---------------------------------------------------------------------------
// getVisibleAdvancedJsonFields
// ---------------------------------------------------------------------------

describe("getVisibleAdvancedJsonFields", () => {
  test("returns empty set for template_fill mode", () => {
    const fields = getVisibleAdvancedJsonFields(makeStep({ output_mode: "template_fill" }));
    expect(fields.size).toBe(0);
  });

  test("returns input_contract and output_contract for standard step", () => {
    const fields = getVisibleAdvancedJsonFields(makeStep());
    expect(fields.has("input_contract")).toBe(true);
    expect(fields.has("output_contract")).toBe(true);
    expect(fields.has("input_config")).toBe(false);
    expect(fields.has("output_config")).toBe(false);
  });

  test("includes input_config for http_get source", () => {
    const fields = getVisibleAdvancedJsonFields(makeStep({ input_source: "http_get" }));
    expect(fields.has("input_config")).toBe(true);
  });

  test("includes input_config for http_post source", () => {
    const fields = getVisibleAdvancedJsonFields(makeStep({ input_source: "http_post" }));
    expect(fields.has("input_config")).toBe(true);
  });

  test("includes output_config for http_post output mode", () => {
    const fields = getVisibleAdvancedJsonFields(makeStep({ output_mode: "http_post" }));
    expect(fields.has("output_config")).toBe(true);
  });

  test("returns empty set for null step", () => {
    const fields = getVisibleAdvancedJsonFields(null);
    expect(fields.size).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// syncDraftsFromStep
// ---------------------------------------------------------------------------

describe("syncDraftsFromStep", () => {
  test("initializes drafts from step values", () => {
    const step = makeStep({ input_contract: { type: "object" } });
    const result = syncDraftsFromStep(step);
    expect(result.drafts.input_contract).toBe('{\n  "type": "object"\n}');
    expect(result.drafts.output_contract).toBe("");
    expect(result.errors).toEqual({});
  });

  test("returns empty drafts for null step", () => {
    const result = syncDraftsFromStep(null);
    expect(result.drafts.input_contract).toBe("");
    expect(result.drafts.output_contract).toBe("");
  });
});

// ---------------------------------------------------------------------------
// syncDraftsFromStepValues
// ---------------------------------------------------------------------------

describe("syncDraftsFromStepValues", () => {
  test("returns null when no changes needed", () => {
    const step = makeStep();
    const drafts = { input_contract: "", output_contract: "", input_config: "", output_config: "" };
    expect(syncDraftsFromStepValues(drafts, {}, step)).toBeNull();
  });

  test("returns updated drafts when step values changed", () => {
    const step = makeStep({ input_contract: { type: "object" } });
    const drafts = { input_contract: "", output_contract: "", input_config: "", output_config: "" };
    const result = syncDraftsFromStepValues(drafts, {}, step);
    expect(result).not.toBeNull();
    expect(result!.input_contract).toBe('{\n  "type": "object"\n}');
  });

  test("skips fields with existing errors", () => {
    const step = makeStep({ input_contract: { type: "object" } });
    const drafts = {
      input_contract: "invalid json",
      output_contract: "",
      input_config: "",
      output_config: ""
    };
    const errors = { input_contract: "some error" };
    const result = syncDraftsFromStepValues(drafts, errors, step);
    expect(result).toBeNull(); // input_contract skipped due to error, others unchanged
  });
});

// ---------------------------------------------------------------------------
// clearHiddenFieldErrors
// ---------------------------------------------------------------------------

describe("clearHiddenFieldErrors", () => {
  test("clears errors for hidden fields", () => {
    const errors = { input_config: "some error", input_contract: "another" };
    const step = makeStep(); // standard step doesn't show input_config
    const result = clearHiddenFieldErrors(errors, step);
    expect(result).not.toBeNull();
    expect(result!.input_config).toBeUndefined();
    expect(result!.input_contract).toBe("another");
  });

  test("returns null when no errors need clearing", () => {
    const errors = { input_contract: "error" };
    const step = makeStep(); // input_contract is visible
    expect(clearHiddenFieldErrors(errors, step)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// parseAdvancedJsonField
// ---------------------------------------------------------------------------

describe("parseAdvancedJsonField", () => {
  const emptyDrafts = {
    input_contract: "",
    output_contract: "",
    input_config: "",
    output_config: ""
  };

  test("parses valid JSON and clears error", () => {
    const result = parseAdvancedJsonField(
      emptyDrafts,
      { input_contract: "old error" },
      "input_contract",
      '{"type": "object"}'
    );
    expect(result.parsed).toEqual({ type: "object" });
    expect(result.parseError).toBeNull();
    expect(result.errors.input_contract).toBeUndefined();
    expect(result.drafts.input_contract).toBe('{"type": "object"}');
  });

  test("sets error for invalid JSON", () => {
    const result = parseAdvancedJsonField(emptyDrafts, {}, "input_contract", "{invalid");
    expect(result.parsed).toBeNull();
    expect(result.parseError).toBeTruthy();
    expect(result.errors.input_contract).toBeTruthy();
  });

  test("treats empty input as null value", () => {
    const result = parseAdvancedJsonField(emptyDrafts, {}, "input_contract", "  ");
    expect(result.parsed).toBeNull();
    expect(result.parseError).toBeNull();
  });
});

describe("formatAdvancedJsonDraftField", () => {
  const emptyDrafts = {
    input_contract: "",
    output_contract: "",
    input_config: "",
    output_config: ""
  };

  test("formats a valid draft and returns the parsed value", () => {
    const result = formatAdvancedJsonDraftField(
      { ...emptyDrafts, output_contract: '{"type":"object","required":["name"]}' },
      {},
      "output_contract"
    );

    expect(result.formatted).toBe(true);
    expect(result.parseError).toBeNull();
    expect(result.parsed).toEqual({ type: "object", required: ["name"] });
    expect(result.drafts.output_contract).toBe(
      '{\n  "type": "object",\n  "required": [\n    "name"\n  ]\n}'
    );
  });

  test("keeps the draft and returns an error for invalid JSON", () => {
    const result = formatAdvancedJsonDraftField(
      { ...emptyDrafts, input_contract: "{invalid" },
      {},
      "input_contract"
    );

    expect(result.formatted).toBe(false);
    expect(result.parseError).toBeTruthy();
    expect(result.drafts.input_contract).toBe("{invalid");
    expect(result.errors.input_contract).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// getErrorFields
// ---------------------------------------------------------------------------

describe("getErrorFields", () => {
  test("returns fields with errors", () => {
    expect(getErrorFields({ input_contract: "error", output_config: "error" })).toEqual([
      "input_contract",
      "output_config"
    ]);
  });

  test("returns empty array when no errors", () => {
    expect(getErrorFields({})).toEqual([]);
  });
});
