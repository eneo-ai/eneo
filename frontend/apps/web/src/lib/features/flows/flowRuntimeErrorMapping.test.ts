import { describe, expect, it } from "vitest";
import { IntricError } from "@intric/intric-js";

import {
  describeFlowApiError,
  getFlowRuntimeErrorMessage,
  classifyUploadError,
  getUploadErrorHint,
  friendlyMimeNames,
  FLOW_API_ERROR_CODES,
  getReviewPolicyAffectedStepsFromRunError,
  getReviewPolicyErrorStepsFromDefinitionSnapshot,
  isReviewPolicyInvalidRunError,
  isReviewPolicyRunErrorRelevantForStep,
  isReviewPolicyRunErrorStepExact,
  reviewPolicyRunErrorStepOrder
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

  it("maps rerun unsupported code through the Flow API descriptor", () => {
    const error = new IntricError(
      "rerun unsupported",
      "RESPONSE",
      400,
      0,
      { code: "flow_run_rerun_step_inputs_unsupported" },
      { endpoint: "POST@test" }
    );

    expect(describeFlowApiError(error)).toMatchObject({
      code: "flow_run_rerun_step_inputs_unsupported",
      messageKey: "flow_error_flow_run_rerun_step_inputs_unsupported"
    });
    expect(getFlowRuntimeErrorMessage(error, "fallback")).not.toBe("fallback");
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

  it.each([
    ["Step 1: review_policy is invalid.", 1],
    ["Step 1 (Draft review): review_policy is invalid.", 1],
    ["Step 10: review_policy is invalid.", 10]
  ])("extracts the backend step prefix from %s", (message, expected) => {
    expect(reviewPolicyRunErrorStepOrder(message)).toBe(expected);
  });

  it.each(["Step abc: review_policy is invalid.", "This step is invalid."])(
    "returns null when the message has no numeric backend step prefix",
    (message) => {
      expect(reviewPolicyRunErrorStepOrder(message)).toBeNull();
    }
  );

  it("detects the review policy invalid run error token", () => {
    expect(isReviewPolicyInvalidRunError("Step 1: review_policy is invalid.")).toBe(true);
    expect(isReviewPolicyInvalidRunError("This step is invalid.")).toBe(false);
  });

  it("returns the exact affected step when the backend message carries a step order", () => {
    expect(
      getReviewPolicyAffectedStepsFromRunError(
        "Step 10 (Final review): review_policy is invalid.",
        reviewSteps
      )
    ).toEqual([{ step_order: 10, user_description: "Final review" }]);
  });

  it("preserves the backend step order when the current flow draft cannot label it", () => {
    expect(
      getReviewPolicyAffectedStepsFromRunError("Step 3: review_policy is invalid.", reviewSteps)
    ).toEqual([{ step_order: 3, user_description: null }]);
  });

  it("falls back to all current review steps for old generic review policy errors", () => {
    expect(
      getReviewPolicyAffectedStepsFromRunError(
        "Some failure (review_policy is invalid)",
        reviewSteps
      )
    ).toEqual([
      { step_order: 1, user_description: "Draft review" },
      { step_order: 10, user_description: "Final review" }
    ]);
  });

  it("returns no affected steps for unrelated errors", () => {
    expect(getReviewPolicyAffectedStepsFromRunError("This step is invalid.", reviewSteps)).toEqual(
      []
    );
  });

  it("marks exact review policy run errors separately from candidate fallback errors", () => {
    expect(isReviewPolicyRunErrorStepExact("Step 10: review_policy is invalid.")).toBe(true);
    expect(isReviewPolicyRunErrorStepExact("Some failure (review_policy is invalid)")).toBe(false);
  });

  it("keeps generic review policy errors on review steps only", () => {
    expect(
      isReviewPolicyRunErrorRelevantForStep("Some failure (review_policy is invalid)", 1, {
        mode: "view"
      })
    ).toBe(true);
    expect(
      isReviewPolicyRunErrorRelevantForStep("Some failure (review_policy is invalid)", 2, null)
    ).toBe(false);
  });

  it("keeps exact review policy errors on the backend-reported step only", () => {
    expect(
      isReviewPolicyRunErrorRelevantForStep("Step 10: review_policy is invalid.", 10, null)
    ).toBe(true);
    expect(
      isReviewPolicyRunErrorRelevantForStep("Step 10: review_policy is invalid.", 1, {
        mode: "view"
      })
    ).toBe(false);
  });

  it("keeps unrelated errors visible for any step", () => {
    expect(isReviewPolicyRunErrorRelevantForStep("Provider timeout.", 1, null)).toBe(true);
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
