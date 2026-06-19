import { describe, expect, it } from "vitest";
import { IntricError } from "@intric/intric-js";

import {
  describeFlowRunError,
  describeFlowApiError,
  getFlowRuntimeErrorMessage,
  classifyUploadError,
  getUploadErrorHint,
  friendlyMimeNames,
  FLOW_API_ERROR_CODE,
  FLOW_API_ERROR_CODES,
  getReviewPolicyAffectedStepsFromRunError,
  getReviewPolicyErrorStepsFromDefinitionSnapshot,
  getFlowRuntimeErrorMessageByCode,
  isReviewPolicyInvalidRunError,
  isReviewPolicyRunErrorRelevantForStep,
  isReviewPolicyRunErrorStepExact,
  reviewPolicyRunErrorStepOrder,
  type FlowRunError
} from "./flowRuntimeErrorMapping";

describe("flowRuntimeErrorMapping", () => {
  it("describes required runtime input errors with step context", () => {
    const error = new IntricError(
      "Required runtime input files are missing.",
      "RESPONSE",
      400,
      0,
      { code: "flow_run_required_step_input_missing", context: { step_ids: ["step-1"] } },
      { endpoint: "POST@test" }
    );

    expect(describeFlowApiError(error)).toEqual({
      code: "flow_run_required_step_input_missing",
      messageKey: "flow_error_flow_run_required_step_input_missing",
      context: { step_ids: ["step-1"] }
    });
  });

  it("describes review typed contract errors with review context", () => {
    const error = new IntricError(
      "Review checkpoint step 1 output: 'summary' is a required property",
      "RESPONSE",
      400,
      0,
      {
        code: "typed_io_contract_violation",
        context: {
          checkpoint_id: "checkpoint-1",
          step_id: "step-1",
          step_order: 1,
          payload_field: "structured"
        }
      },
      { endpoint: "PATCH@test" }
    );

    expect(describeFlowApiError(error)).toEqual({
      code: "typed_io_contract_violation",
      messageKey: "flow_error_typed_io_contract_violation",
      context: {
        checkpoint_id: "checkpoint-1",
        step_id: "step-1",
        step_order: 1,
        payload_field: "structured"
      }
    });
  });

  it("describes expired review errors with deadline context", () => {
    const error = new IntricError(
      "Review checkpoint has expired.",
      "RESPONSE",
      400,
      0,
      {
        code: "flow_review_expired",
        context: {
          checkpoint_id: "checkpoint-1",
          state: "awaiting_review",
          expires_at: "2026-05-14T09:30:00Z",
          expired_at: "2026-05-14T09:31:00Z"
        }
      },
      { endpoint: "POST@test" }
    );

    expect(describeFlowApiError(error)).toEqual({
      code: "flow_review_expired",
      messageKey: "flow_error_flow_review_expired",
      context: {
        checkpoint_id: "checkpoint-1",
        state: "awaiting_review",
        expires_at: "2026-05-14T09:30:00Z",
        expired_at: "2026-05-14T09:31:00Z"
      }
    });
  });

  it("returns null for non-Flow API errors", () => {
    expect(describeFlowApiError(new Error("plain error"))).toBeNull();
  });

  it("has descriptors for every frontend-owned Flow API error code", () => {
    for (const code of FLOW_API_ERROR_CODES) {
      const error = new IntricError(code, "RESPONSE", 400, 0, { code }, { endpoint: "POST@test" });

      expect(describeFlowApiError(error)?.messageKey).toBe(`flow_error_${code}`);
    }
  });

  it("describes persisted run errors with generated Flow API codes", () => {
    const error: FlowRunError = {
      schema_version: 1,
      code: FLOW_API_ERROR_CODE.STEP_EXECUTION_FAILED,
      message: "Step 2: typed input/output validation failed.",
      source: "executor_failed",
      step_order: 2
    };

    expect(describeFlowRunError(error)).toEqual({
      code: FLOW_API_ERROR_CODE.STEP_EXECUTION_FAILED,
      messageKey: "flow_error_flow_step_execution_failed",
      context: { step_order: 2 }
    });
  });

  it("returns null for unknown persisted run error codes", () => {
    const error: FlowRunError = {
      schema_version: 1,
      code: "provider_timeout",
      message: "Provider timed out.",
      source: "executor_failed"
    };

    expect(describeFlowRunError(error)).toBeNull();
  });

  it("localizes every generated Flow API error code by code", () => {
    for (const code of FLOW_API_ERROR_CODES) {
      expect(getFlowRuntimeErrorMessageByCode(code)).toBeTruthy();
    }
  });

  it("returns null for unknown run error codes so callers can show the stored message", () => {
    expect(getFlowRuntimeErrorMessageByCode("provider_timeout")).toBeNull();
  });

  it("uses the structured response code over the legacy client code", () => {
    const error = new IntricError(
      "stale",
      "RESPONSE",
      400,
      0,
      { code: "flow_review_stale_revision" },
      { endpoint: "PATCH@test" }
    );
    Object.defineProperty(error, "code", { value: "flow_template_not_accessible" });

    expect(describeFlowApiError(error)).toMatchObject({
      code: "flow_review_stale_revision",
      messageKey: "flow_error_flow_review_stale_revision"
    });
  });

  it("maps template access code through the Flow API descriptor", () => {
    const error = new IntricError(
      "forbidden",
      "RESPONSE",
      403,
      0,
      { code: "flow_template_not_accessible" },
      { endpoint: "POST@test" }
    );

    expect(describeFlowApiError(error)).toMatchObject({
      code: "flow_template_not_accessible",
      messageKey: "flow_error_flow_template_not_accessible"
    });
    expect(getFlowRuntimeErrorMessage(error, "fallback")).not.toBe("fallback");
  });

  it.each([
    [
      "flow_run_access_denied",
      [
        "You do not have access to this flow run.",
        "Du har inte åtkomst till den här flödeskörningen."
      ]
    ],
    [
      "flow_run_evidence_forbidden",
      [
        "You do not have permission to view evidence for this run.",
        "Du har inte behörighet att visa evidens för den här körningen."
      ]
    ],
    [
      "flow_run_evidence_raw_export_forbidden",
      [
        "Raw evidence export is blocked by policy for this run.",
        "Råexport av evidens blockeras av policy för den här körningen."
      ]
    ]
  ])("maps %s through the localized Flow API descriptor", (code, messages) => {
    const error = new IntricError(
      "forbidden",
      "RESPONSE",
      403,
      0,
      { code },
      { endpoint: "GET@test" }
    );

    expect(describeFlowApiError(error)).toMatchObject({
      code,
      messageKey: `flow_error_${code}`
    });
    expect(messages).toContain(getFlowRuntimeErrorMessage(error, "fallback"));
  });

  it("maps invalid rerun step inputs through the Flow API descriptor", () => {
    const error = new IntricError(
      "Rerun step_inputs may only target the rerun root step.",
      "RESPONSE",
      400,
      0,
      {
        code: "flow_run_rerun_step_inputs_invalid",
        context: { step_ids: ["downstream-step"] }
      },
      { endpoint: "POST@test" }
    );

    expect(describeFlowApiError(error)).toMatchObject({
      code: "flow_run_rerun_step_inputs_invalid",
      messageKey: "flow_error_flow_run_rerun_step_inputs_invalid",
      context: { step_ids: ["downstream-step"] }
    });
    expect([
      "Rerun files can only be attached to the step being rerun. Remove files from other steps and try again.",
      "Filer vid omkörning kan bara kopplas till steget som körs om. Ta bort filer från andra steg och försök igen."
    ]).toContain(getFlowRuntimeErrorMessage(error, "fallback"));
  });

  it.each([
    [
      "flow_run_invalid_idempotency_key",
      [
        "The retry key is empty or too long. Send a key between 1 and 255 characters.",
        "Nyckeln för säkra omförsök är tom eller för lång. Skicka en nyckel med 1 till 255 tecken."
      ]
    ],
    [
      "flow_run_file_not_bound_to_flow",
      [
        "One or more selected files were uploaded for another flow. Upload them through this flow and try again.",
        "En eller flera valda filer laddades upp för ett annat flöde. Ladda upp dem via det här flödet och försök igen."
      ]
    ],
    [
      "flow_run_rerun_step_incomplete",
      [
        "The selected rerun step does not have a completed current result. Reload the run and choose a completed step.",
        "Det valda omkörningssteget har inget slutfört aktuellt resultat. Läs om körningen och välj ett slutfört steg."
      ]
    ]
  ])("maps newly cataloged %s through the localized Flow API descriptor", (code, messages) => {
    const error = new IntricError(code, "RESPONSE", 400, 0, { code }, { endpoint: "POST@test" });

    expect(describeFlowApiError(error)).toMatchObject({
      code,
      messageKey: `flow_error_${code}`
    });
    expect(messages).toContain(getFlowRuntimeErrorMessage(error, "fallback"));
  });

  it("maps invalid published form schema errors through the Flow API descriptor", () => {
    const error = new IntricError(
      "Published flow form schema is invalid.",
      "RESPONSE",
      400,
      0,
      { code: "flow_published_form_schema_invalid" },
      { endpoint: "GET@test" }
    );

    expect(describeFlowApiError(error)).toMatchObject({
      code: "flow_published_form_schema_invalid",
      messageKey: "flow_error_flow_published_form_schema_invalid"
    });
    expect(getFlowRuntimeErrorMessage(error, "fallback")).not.toBe("fallback");
  });
});

describe("review policy run error helpers", () => {
  const reviewSteps = [
    {
      step_order: 1,
      user_description: "Draft review",
      review_policy: { mode: "view" }
    },
    {
      step_order: 10,
      user_description: "Final review",
      review_policy: { mode: "edit" }
    },
    {
      step_order: 11,
      user_description: "No review",
      review_policy: null
    }
  ];

  const reviewPolicyError = (overrides: Partial<FlowRunError> = {}): FlowRunError => ({
    schema_version: 1,
    code: FLOW_API_ERROR_CODE.REVIEW_POLICY_INVALID,
    message: "Step 10 (Final review): review_policy is invalid.",
    source: "invalid_flow_definition",
    step_order: 10,
    details: { step_description: "Final review" },
    ...overrides
  });

  it("reads the affected step order from the structured run error", () => {
    expect(reviewPolicyRunErrorStepOrder(reviewPolicyError({ step_order: 1 }))).toBe(1);
    expect(reviewPolicyRunErrorStepOrder(reviewPolicyError({ step_order: null }))).toBeNull();
  });

  it("detects the review policy invalid run error token", () => {
    expect(isReviewPolicyInvalidRunError(reviewPolicyError())).toBe(true);
    expect(
      isReviewPolicyInvalidRunError(
        reviewPolicyError({ code: FLOW_API_ERROR_CODE.DEFINITION_INVALID, step_order: null })
      )
    ).toBe(false);
  });

  it("returns the exact affected step when the backend message carries a step order", () => {
    expect(getReviewPolicyAffectedStepsFromRunError(reviewPolicyError(), reviewSteps)).toEqual([
      { step_order: 10, user_description: "Final review" }
    ]);
  });

  it("preserves the backend step order when the current flow draft cannot label it", () => {
    expect(
      getReviewPolicyAffectedStepsFromRunError(reviewPolicyError({ step_order: 3 }), reviewSteps)
    ).toEqual([{ step_order: 3, user_description: null }]);
  });

  it("falls back to all current review steps when the structured error has no step order", () => {
    expect(
      getReviewPolicyAffectedStepsFromRunError(reviewPolicyError({ step_order: null }), reviewSteps)
    ).toEqual([
      { step_order: 1, user_description: "Draft review" },
      { step_order: 10, user_description: "Final review" }
    ]);
  });

  it("returns no affected steps for unrelated errors", () => {
    expect(
      getReviewPolicyAffectedStepsFromRunError(
        reviewPolicyError({ code: FLOW_API_ERROR_CODE.DEFINITION_INVALID }),
        reviewSteps
      )
    ).toEqual([]);
  });

  it("marks exact review policy run errors separately from candidate fallback errors", () => {
    expect(isReviewPolicyRunErrorStepExact(reviewPolicyError())).toBe(true);
    expect(isReviewPolicyRunErrorStepExact(reviewPolicyError({ step_order: null }))).toBe(false);
  });

  it("keeps generic review policy errors on review steps only", () => {
    expect(
      isReviewPolicyRunErrorRelevantForStep(reviewPolicyError({ step_order: null }), 1, {
        mode: "view"
      })
    ).toBe(true);
    expect(
      isReviewPolicyRunErrorRelevantForStep(reviewPolicyError({ step_order: null }), 2, null)
    ).toBe(false);
  });

  it("keeps exact review policy errors on the backend-reported step only", () => {
    expect(isReviewPolicyRunErrorRelevantForStep(reviewPolicyError(), 10, null)).toBe(true);
    expect(
      isReviewPolicyRunErrorRelevantForStep(reviewPolicyError(), 1, {
        mode: "view"
      })
    ).toBe(false);
  });

  it("keeps unrelated errors visible for any step", () => {
    expect(
      isReviewPolicyRunErrorRelevantForStep(
        reviewPolicyError({ code: "provider_timeout", step_order: null }),
        1,
        null
      )
    ).toBe(true);
  });

  it("reads review policy step metadata from a definition snapshot", () => {
    expect(
      getReviewPolicyErrorStepsFromDefinitionSnapshot([
        {
          step_order: 1,
          user_description: "Draft review",
          review_policy: { mode: "view" }
        },
        {
          step_order: "invalid",
          user_description: "Invalid order",
          review_policy: { mode: "edit" }
        },
        null
      ])
    ).toEqual([
      {
        step_order: 1,
        user_description: "Draft review",
        review_policy: { mode: "view" }
      }
    ]);
  });
});

describe("classifyUploadError", () => {
  it("detects timeout errors", () => {
    expect(classifyUploadError("Upload timed out after 120s")).toBe("timeout");
    expect(classifyUploadError("Request timeout")).toBe("timeout");
    expect(classifyUploadError("Upload did not start within 600s")).toBe("timeout");
    expect(classifyUploadError("Upload stalled for 120s")).toBe("timeout");
    expect(classifyUploadError("Server did not respond within 120s")).toBe("timeout");
  });

  it("detects file size errors", () => {
    expect(classifyUploadError("File too large")).toBe("file_too_large");
    expect(classifyUploadError("Max filstorlek: 195 MB")).toBe("file_too_large");
  });

  it("detects network errors", () => {
    expect(classifyUploadError("Network error")).toBe("network");
    expect(classifyUploadError("Failed to fetch")).toBe("network");
  });

  it("returns unknown for unrecognised errors", () => {
    expect(classifyUploadError("Something went wrong")).toBe("unknown");
  });
});

describe("getUploadErrorHint", () => {
  it("returns a hint for timeout", () => {
    expect(getUploadErrorHint("timeout")).toContain("Försök igen");
  });

  it("returns empty string for unknown", () => {
    expect(getUploadErrorHint("unknown")).toBe("");
  });
});

describe("friendlyMimeNames", () => {
  it("maps known MIME types to friendly names", () => {
    expect(friendlyMimeNames(["application/pdf", "text/csv"])).toEqual(["PDF", "CSV"]);
  });

  it("passes through unknown MIME types", () => {
    expect(friendlyMimeNames(["application/x-custom"])).toEqual(["application/x-custom"]);
  });
});
