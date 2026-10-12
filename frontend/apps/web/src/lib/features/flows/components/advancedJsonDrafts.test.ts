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
  type AdvancedJsonErrors
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
    const errors: AdvancedJsonErrors = { input_contract: "syntax" };
    const result = syncDraftsFromStepValues(drafts, errors, step);
    expect(result).toBeNull(); // input_contract skipped due to error, others unchanged
  });
});

// ---------------------------------------------------------------------------
// clearHiddenFieldErrors
// ---------------------------------------------------------------------------

describe("clearHiddenFieldErrors", () => {
  test("clears errors for hidden fields", () => {
    const errors: AdvancedJsonErrors = { input_config: "syntax", input_contract: "not_object" };
    const step = makeStep(); // standard step doesn't show input_config
    const result = clearHiddenFieldErrors(errors, step);
    expect(result).not.toBeNull();
    expect(result!.input_config).toBeUndefined();
    expect(result!.input_contract).toBe("not_object");
  });

  test("returns null when no errors need clearing", () => {
    const errors: AdvancedJsonErrors = { input_contract: "syntax" };
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
      { input_contract: "syntax" },
      "input_contract",
      '{"type": "object"}'
    );
    expect(result).toMatchObject({ parsed: { type: "object" }, problem: null });
    expect(result.errors.input_contract).toBeUndefined();
    expect(result.drafts.input_contract).toBe('{"type": "object"}');
  });

  test("sets error for invalid JSON", () => {
    const result = parseAdvancedJsonField(emptyDrafts, {}, "input_contract", "{invalid");
    expect(result.problem).toBe("syntax");
    expect(result).not.toHaveProperty("parsed");
    expect(result.errors.input_contract).toBe("syntax");
  });

  // Kills: storing whatever JSON.parse returns. The server keeps an object or
  // nothing in these fields, so a list, number, text or boolean must stop here.
  test.each(["[1, 2]", "42", '"text"', "true"])(
    "refuses JSON that is not an object: %s",
    (draft) => {
      const result = parseAdvancedJsonField(emptyDrafts, {}, "output_config", draft);
      expect(result.problem).toBe("not_object");
      expect(result).not.toHaveProperty("parsed");
      expect(result.errors.output_config).toBe("not_object");
      expect(result.drafts.output_config).toBe(draft);
    }
  );

  // Kills: counting the JSON word null as "not an object"; it empties the field.
  test.each(["  ", "null"])("treats %j as an empty value", (draft) => {
    const result = parseAdvancedJsonField(
      emptyDrafts,
      { input_contract: "not_object" },
      "input_contract",
      draft
    );
    expect(result).toMatchObject({ parsed: null, problem: null });
    expect(result.errors.input_contract).toBeUndefined();
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
    expect(result).toMatchObject({ parsed: { type: "object", required: ["name"] }, problem: null });
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
    expect(result.problem).toBe("syntax");
    expect(result.drafts.input_contract).toBe("{invalid");
    expect(result.errors.input_contract).toBe("syntax");
  });

  // Kills: formatting on the value alone. An emptied or refused draft has
  // nothing to lay out, and its text must stay as typed.
  test.each(["null", "[1, 2]"])("leaves %j as typed", (draft) => {
    const result = formatAdvancedJsonDraftField(
      { ...emptyDrafts, output_config: draft },
      {},
      "output_config"
    );

    expect(result.formatted).toBe(false);
    expect(result.drafts.output_config).toBe(draft);
  });
});

// ---------------------------------------------------------------------------
// getErrorFields
// ---------------------------------------------------------------------------

describe("getErrorFields", () => {
  test("returns fields with errors", () => {
    expect(getErrorFields({ input_contract: "syntax", output_config: "not_object" })).toEqual([
      "input_contract",
      "output_config"
    ]);
  });

  test("returns empty array when no errors", () => {
    expect(getErrorFields({})).toEqual([]);
  });
});
