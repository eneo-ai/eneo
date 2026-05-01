import { describe, expect, it } from "vitest";

import {
  buildFlowRunIntent,
  buildFlowRunInputPayload,
  buildStepInputsPayload,
  computeReusedFlowRunInput,
  getBlockingTemplateReadinessItems,
  getFlowRunReviewFieldValue,
  getMissingFlowRunRequiredFields,
  normalizeTemplateReadiness,
  readFlowRunFieldMultiValue,
  readFlowRunFieldValue
} from "./flowRunContract";
import type { NormalizedFlowFormField } from "./flowFormSchema";

function field(
  name: string,
  overrides: Partial<NormalizedFlowFormField> = {}
): NormalizedFlowFormField {
  return {
    name,
    type: "text",
    required: false,
    options: [],
    order: 1,
    ...overrides
  };
}

describe("flowRunContract helpers", () => {
  it("builds canonical step_inputs payload from uploaded files", () => {
    expect(
      buildStepInputsPayload({
        "step-1": [{ id: "file-1" }, { id: "file-2" }],
        "step-2": []
      })
    ).toEqual({
      "step-1": { file_ids: ["file-1", "file-2"] }
    });
  });

  it("builds a canonical flow run intent payload", () => {
    expect(
      buildFlowRunIntent({
        publishedFlowVersion: 7,
        inputPayloadJson: { text: "hello" },
        stepInputs: {
          "step-1": { file_ids: ["file-1"] }
        }
      })
    ).toEqual({
      expected_flow_version: 7,
      input_payload_json: { text: "hello" },
      step_inputs: {
        "step-1": { file_ids: ["file-1"] }
      }
    });
  });

  it("normalizes template readiness values into a list", () => {
    expect(normalizeTemplateReadiness(null)).toEqual([]);
    expect(
      normalizeTemplateReadiness({
        step_id: "step-1",
        status: "ready"
      })
    ).toHaveLength(1);
  });

  it("marks unavailable and needs_action template states as blocking", () => {
    expect(
      getBlockingTemplateReadinessItems([
        { step_id: "step-1", status: "ready" },
        { step_id: "step-2", status: "unavailable" },
        { step_id: "step-3", status: "needs_action" }
      ])
    ).toEqual([
      { step_id: "step-2", status: "unavailable" },
      { step_id: "step-3", status: "needs_action" }
    ]);
  });

  it("reads scalar and multiselect form field values", () => {
    const values = {
      name: "Ada",
      empty: null,
      roles: ["admin", 7],
      tags: "alpha, beta ,, gamma"
    };

    expect(readFlowRunFieldValue(values, field("name"))).toBe("Ada");
    expect(readFlowRunFieldValue(values, field("roles", { type: "multiselect" }))).toBe("");
    expect(readFlowRunFieldValue(values, field("empty"))).toBe("");
    expect(readFlowRunFieldMultiValue(values, field("roles", { type: "multiselect" }))).toEqual([
      "admin",
      "7"
    ]);
    expect(readFlowRunFieldMultiValue(values, field("tags", { type: "multiselect" }))).toEqual([
      "alpha",
      "beta",
      "gamma"
    ]);
  });

  it("detects missing required form fields from the current contract fields", () => {
    const fields = [
      field("name", { required: true }),
      field("count", { type: "number", required: true }),
      field("roles", { type: "multiselect", required: true }),
      field("comma_roles", { type: "multiselect", required: true }),
      field("optional")
    ];

    expect(
      getMissingFlowRunRequiredFields(
        {
          name: "  ",
          count: 0,
          roles: [],
          comma_roles: "admin, editor",
          stale: "ignored"
        },
        fields
      )
    ).toEqual([fields[0], fields[2]]);
  });

  it("formats review field values", () => {
    const values = {
      name: "  Ada  ",
      roles: ["admin", "editor"]
    };

    expect(getFlowRunReviewFieldValue(values, field("name"))).toBe("Ada");
    expect(getFlowRunReviewFieldValue(values, field("roles", { type: "multiselect" }))).toBe(
      "admin, editor"
    );
  });

  it("computes reused form values from prior input without dropping stale keys", () => {
    const result = computeReusedFlowRunInput({
      currentFormValues: {
        name: "typed",
        stale: "kept",
        roles: ["old"]
      },
      currentFreeformText: "typed text",
      lastInputPayload: {
        name: "Ada",
        roles: "admin, editor",
        nullable_roles: null
      },
      formFields: [
        field("name"),
        field("missing"),
        field("roles", { type: "multiselect" }),
        field("nullable_roles", { type: "multiselect" })
      ],
      hasFormFields: true,
      showFreeformTextInput: false
    });

    expect(result).toEqual({
      formValues: {
        name: "Ada",
        missing: "",
        roles: ["admin", "editor"],
        nullable_roles: [],
        stale: "kept"
      },
      freeformText: "typed text"
    });
  });

  it("computes reused freeform text from text before falling back to JSON", () => {
    expect(
      computeReusedFlowRunInput({
        currentFormValues: { name: "kept" },
        currentFreeformText: "typed text",
        lastInputPayload: { text: "previous text", other: true },
        formFields: [],
        hasFormFields: false,
        showFreeformTextInput: true
      })
    ).toEqual({
      formValues: { name: "kept" },
      freeformText: "previous text"
    });

    expect(
      computeReusedFlowRunInput({
        currentFormValues: {},
        currentFreeformText: "",
        lastInputPayload: { other: true },
        formFields: [],
        hasFormFields: false,
        showFreeformTextInput: true
      }).freeformText
    ).toBe('{"other":true}');
  });

  it("builds form and freeform input payloads", () => {
    const fields = [
      field("name"),
      field("quantity", { type: "number" }),
      field("negative", { type: "number" }),
      field("empty_number", { type: "number" }),
      field("roles", { type: "multiselect" })
    ];

    expect(
      buildFlowRunInputPayload({
        formValues: {
          name: "Ada",
          quantity: "0",
          negative: "-3.14",
          empty_number: "   ",
          roles: ["admin", "editor"]
        },
        freeformText: "ignored",
        formFields: fields,
        hasFormFields: true,
        showFreeformTextInput: false
      })
    ).toEqual({
      name: "Ada",
      quantity: 0,
      negative: -3.14,
      empty_number: "",
      roles: ["admin", "editor"]
    });

    expect(
      buildFlowRunInputPayload({
        formValues: {},
        freeformText: "Run this flow",
        formFields: [],
        hasFormFields: false,
        showFreeformTextInput: true
      })
    ).toEqual({ text: "Run this flow" });
  });
});
