import { EneoError } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import {
  describeClassificationRefusal,
  getValidationIssueMessage,
  parseServerValidationIdentity,
  parseValidationError,
  type ClassificationRefusal
} from "./flowStepValidationMessages";

describe("parseServerValidationIdentity", () => {
  it("reads the identity from a REAL EneoError transport shape", () => {
    // The backend GeneralError body lands in EneoError.response.
    const error = new EneoError(
      "Step 3: output_mode 'http_post' is only supported on the last step.",
      "RESPONSE",
      400,
      0,
      {
        message: "Step 3: output_mode 'http_post' is only supported on the last step.",
        eneo_error_code: 0,
        code: "flow_http_post_output_must_be_terminal",
        context: { issue_code: "flow_http_post_output_must_be_terminal", step_order: 3 }
      },
      { endpoint: "/api/v1/flows/x" }
    );
    expect(parseServerValidationIdentity(error)).toEqual({
      code: "flow_http_post_output_must_be_terminal",
      stepOrder: 3,
      field: null,
      reference: null
    });
  });

  it("reads the motivating step_input binding rejection", () => {
    const error = new EneoError(
      "Step 3: explicit question bindings must reference step_input.* when runtime input is enabled.",
      "RESPONSE",
      400,
      0,
      {
        message: "…",
        eneo_error_code: 0,
        code: "flow_input_binding_runtime_input_unused",
        context: { issue_code: "flow_input_binding_runtime_input_unused", step_order: 3 }
      },
      { endpoint: "/api/v1/flows/x" }
    );
    const identity = parseServerValidationIdentity(error);
    expect(identity).toEqual({
      code: "flow_input_binding_runtime_input_unused",
      stepOrder: 3,
      field: null,
      reference: null
    });
    // And the code translates (not the bare code, not the raw sentence).
    expect(getValidationIssueMessage(identity!.code)).not.toBe(identity!.code);
  });

  it("never treats a symbolic code without issue_code as validation", () => {
    const error = new EneoError("boom", "RESPONSE", 400, 0, {
      message: "boom",
      eneo_error_code: 0,
      code: "some_domain_error"
    });
    expect(parseServerValidationIdentity(error)).toBeNull();
    expect(parseServerValidationIdentity({})).toBeNull();
  });
});

describe("server validation banner keys", () => {
  it("parses flow:server keys into step issues carrying the raw detail", () => {
    const parsed = parseValidationError("flow:server:flow_http_post_output_must_be_terminal:3", [
      "Step 3: output_mode 'http_post' is only supported on the last step."
    ]);
    expect(parsed).toMatchObject({
      kind: "step",
      code: "flow_http_post_output_must_be_terminal",
      stepOrder: 3,
      detail: "Step 3: output_mode 'http_post' is only supported on the last step."
    });
  });

  it("translates the owner's two example codes", () => {
    // The translated copy must differ from the bare code (i.e. a mapping
    // exists); exact wording is owned by the message catalog.
    for (const code of [
      "flow_http_post_output_must_be_terminal",
      "flow_input_binding_runtime_input_unused",
      "flow_input_alias_not_received",
      "flow_step_invalid"
    ]) {
      expect(getValidationIssueMessage(code)).not.toBe(code);
    }
  });
});

it.each([
  {
    field: "input_bindings.question",
    reference: "step_9",
    expectedField: "input_bindings.question",
    expectedReference: "step_9"
  },
  { field: "", reference: 9, expectedField: null, expectedReference: null }
])(
  "reads only non-empty binding context strings",
  ({ field, reference, expectedField, expectedReference }) => {
    expect(
      parseServerValidationIdentity({
        response: {
          context: {
            issue_code: "flow_input_binding_unknown_step_order",
            step_order: 3,
            field,
            reference
          }
        }
      })
    ).toEqual({
      code: "flow_input_binding_unknown_step_order",
      stepOrder: 3,
      field: expectedField,
      reference: expectedReference
    });
  }
);

describe("security classification refusals", () => {
  const MISMATCH = "flow_step_security_classification_mismatch";
  const WRITE_DOWN = "flow_step_output_classification_write_down";

  function refusalError(code: string, context: Record<string, unknown>) {
    return new EneoError(
      "Step 3: assistant model does not meet the required security classification.",
      "RESPONSE",
      400,
      0,
      {
        message: "Step 3: assistant model does not meet the required security classification.",
        eneo_error_code: 0,
        code,
        context: { issue_code: code, step_order: 3, ...context }
      },
      { endpoint: "/api/v1/flows/x" }
    );
  }

  const names = {
    stepLabel: (order: number) =>
      ({ 1: "Transkribera", 2: "Sammanfatta" })[order] ?? `Steg ${order}`,
    modelName: (id: string) => ({ "model-a": "Modell A", "model-b": "Modell B" })[id]
  };

  it("carries the refusal facts on the parsed identity", () => {
    const identity = parseServerValidationIdentity(
      refusalError(MISMATCH, {
        step_id: "step-3",
        required_level: 3,
        current_level: 2,
        cause: "reads",
        source_step_orders: [1],
        qualifying_model_ids: ["model-a", "model-b"]
      })
    );

    expect(identity).toEqual({
      code: MISMATCH,
      stepOrder: 3,
      field: null,
      reference: null,
      classification: {
        kind: "model_below_required",
        requiredLevel: 3,
        currentLevel: 2,
        cause: "reads",
        sourceStepOrders: [1],
        qualifyingModelIds: ["model-a", "model-b"]
      }
    });
  });

  it("reads a write-down and a model that has no level", () => {
    const writeDown = parseServerValidationIdentity(
      refusalError(WRITE_DOWN, {
        required_level: 3,
        current_level: 1,
        cause: "knowledge",
        source_step_orders: []
      })
    );
    expect(writeDown?.classification).toEqual({
      kind: "output_write_down",
      requiredLevel: 3,
      currentLevel: 1,
      cause: "knowledge",
      sourceStepOrders: [],
      qualifyingModelIds: []
    });

    const unclassified = parseServerValidationIdentity(
      refusalError(MISMATCH, {
        required_level: 2,
        current_level: null,
        cause: "space",
        source_step_orders: [],
        qualifying_model_ids: []
      })
    );
    expect(unclassified?.classification?.currentLevel).toBeNull();
  });

  it.each([
    { name: "an unknown cause", context: { required_level: 3, cause: "mystery" } },
    { name: "a missing required level", context: { cause: "reads" } },
    { name: "a non-numeric level", context: { required_level: "3", cause: "reads" } }
  ])("keeps the identity but no facts for $name", ({ context }) => {
    const identity = parseServerValidationIdentity(refusalError(MISMATCH, context));
    expect(identity?.code).toBe(MISMATCH);
    expect(identity?.classification).toBeUndefined();
  });

  it("gives both codes a translated fallback for a refusal without facts", () => {
    for (const code of [MISMATCH, WRITE_DOWN]) {
      expect(getValidationIssueMessage(code)).not.toBe(code);
    }
    expect(getValidationIssueMessage(MISMATCH)).not.toBe(getValidationIssueMessage(WRITE_DOWN));
  });

  it("says what is read, what the model is cleared for and which models to choose", () => {
    const refusal: ClassificationRefusal = {
      kind: "model_below_required",
      requiredLevel: 3,
      currentLevel: 2,
      cause: "reads",
      sourceStepOrders: [1],
      qualifyingModelIds: ["model-a", "model-b"]
    };

    const message = describeClassificationRefusal(refusal, names);

    expect(message).toContain("K3");
    expect(message).toContain("Transkribera");
    expect(message).toContain("K2");
    expect(message).toContain("Modell A");
    expect(message).toContain("Modell B");
    expect(message).not.toContain("undefined");
  });

  it("names every step a level is read from", () => {
    const message = describeClassificationRefusal(
      {
        kind: "model_below_required",
        requiredLevel: 3,
        currentLevel: 1,
        cause: "reads",
        sourceStepOrders: [1, 2],
        qualifyingModelIds: ["model-a"]
      },
      names
    );

    expect(message).toContain("Transkribera");
    expect(message).toContain("Sammanfatta");
  });

  it("blames the knowledge sources or the space when no read sets the level", () => {
    const base: Omit<ClassificationRefusal, "cause"> = {
      kind: "model_below_required",
      requiredLevel: 3,
      currentLevel: 1,
      sourceStepOrders: [],
      qualifyingModelIds: ["model-a"]
    };
    const knowledge = describeClassificationRefusal({ ...base, cause: "knowledge" }, names);
    const space = describeClassificationRefusal({ ...base, cause: "space" }, names);

    expect(knowledge).toContain("K3");
    expect(space).toContain("K3");
    expect(knowledge).not.toBe(space);
    expect(knowledge).not.toContain("Transkribera");
  });

  it("says a model has no level, and that no model qualifies, instead of an empty list", () => {
    const message = describeClassificationRefusal(
      {
        kind: "model_below_required",
        requiredLevel: 2,
        currentLevel: null,
        cause: "space",
        sourceStepOrders: [],
        qualifyingModelIds: []
      },
      names
    );

    expect(message).toContain("K2");
    expect(message).not.toContain("K0");
    expect(message).not.toContain("null");
    expect(message).not.toContain("Modell A");
  });

  it("does not invent names for models the client does not know", () => {
    const message = describeClassificationRefusal(
      {
        kind: "model_below_required",
        requiredLevel: 3,
        currentLevel: 2,
        cause: "reads",
        sourceStepOrders: [1],
        qualifyingModelIds: ["model-unknown"]
      },
      names
    );

    expect(message).not.toContain("model-unknown");
    expect(message).not.toContain("undefined");
    expect(message).toContain("K3");
  });

  it("explains a write-down with the override and the level the result already carries", () => {
    const message = describeClassificationRefusal(
      {
        kind: "output_write_down",
        requiredLevel: 3,
        currentLevel: 1,
        cause: "reads",
        sourceStepOrders: [1],
        qualifyingModelIds: []
      },
      names
    );

    expect(message).toContain("K1");
    expect(message).toContain("K3");
    expect(message).toContain("Transkribera");
  });
});

describe("the step limit refusal", () => {
  const code = "flow_step_limit_exceeded";
  const raw = "A flow can have at most 256 steps; this one has 257. Remove steps and try again.";

  it("is a flow-scoped refusal that names no step", () => {
    const error = new EneoError(
      raw,
      "RESPONSE",
      400,
      0,
      {
        message: raw,
        eneo_error_code: 0,
        code,
        context: { issue_code: code, step_count: 257, max_steps: 256 }
      },
      { endpoint: "/api/v1/flows/x" }
    );

    expect(parseServerValidationIdentity(error)).toEqual({
      code,
      stepOrder: null,
      field: null,
      reference: null
    });
    expect(parseValidationError(`flow:server:${code}`, [raw])).toMatchObject({
      kind: "flow",
      code,
      detail: raw
    });
  });

  it("has a translated sentence that repeats no number", () => {
    const message = getValidationIssueMessage(code);

    expect(message).not.toBe(code);
    expect(message).not.toMatch(/\d/);
  });
});
