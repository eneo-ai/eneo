import { describe, expect, it } from "vitest";
import { IntricError } from "@intric/intric-js";

import {
  describeFlowApiError,
  getFlowRuntimeErrorMessage,
  classifyUploadError,
  getUploadErrorHint,
  friendlyMimeNames,
  FLOW_API_ERROR_CODES
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
});

describe("classifyUploadError", () => {
  it("detects timeout errors", () => {
    expect(classifyUploadError("Upload timed out after 120s")).toBe("timeout");
    expect(classifyUploadError("Request timeout")).toBe("timeout");
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
