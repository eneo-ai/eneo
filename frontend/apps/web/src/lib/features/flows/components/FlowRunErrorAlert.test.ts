import { render } from "svelte/server";
import { describe, expect, it } from "vitest";

import {
  FLOW_API_ERROR_CODE,
  type FlowRunError
} from "$lib/features/flows/flowRuntimeErrorMapping";
import { m } from "$lib/paraglide/messages";

import FlowRunErrorAlert from "./FlowRunErrorAlert.svelte";

function runError(overrides: Partial<FlowRunError> = {}): FlowRunError {
  return {
    schema_version: 1,
    code: FLOW_API_ERROR_CODE.STEP_EXECUTION_FAILED,
    message: "Step 2: typed input/output validation failed.",
    source: "executor_failed",
    step_order: 2,
    ...overrides
  };
}

describe("FlowRunErrorAlert", () => {
  it("renders the localized catalog message for known run error codes", () => {
    const { body } = render(FlowRunErrorAlert, {
      props: {
        error: runError(),
        message: "Step 2: typed input/output validation failed."
      }
    });

    expect(body).toContain(m.flow_error_flow_step_execution_failed());
    expect(body).not.toContain(m.flow_run_error_desc());
    expect(body).toContain("Step 2: typed input/output validation failed.");
  });

  it("keeps the generic summary for message-only step error alerts", () => {
    const { body } = render(FlowRunErrorAlert, {
      props: {
        message: "Step 1 failed."
      }
    });

    expect(body).toContain(m.flow_run_error_desc());
    expect(body).toContain("Step 1 failed.");
  });

  it("renders the localized catalog message for known step error codes", () => {
    const { body } = render(FlowRunErrorAlert, {
      props: {
        errorCode: FLOW_API_ERROR_CODE.STEP_EXECUTION_FAILED,
        message: "Step 1 failed."
      }
    });

    expect(body).toContain(m.flow_error_flow_step_execution_failed());
    expect(body).not.toContain(m.flow_run_error_desc());
    expect(body).toContain("Step 1 failed.");
  });

  it("localizes typed runtime errors by code while keeping technical detail separate", () => {
    const { body } = render(FlowRunErrorAlert, {
      props: {
        error: runError({
          code: FLOW_API_ERROR_CODE.TYPED_IO_TRANSCRIPTION_FAILED,
          message:
            "Step 1: The transcription provider failed while processing audio (typed_io_transcription_failed).",
          source: "executor_failed",
          step_order: 1
        }),
        errorCode: FLOW_API_ERROR_CODE.TYPED_IO_TRANSCRIPTION_FAILED,
        message: "Step 1: transcription failed for 'utvecklingssamtal.mp3'."
      }
    });

    expect(body).toContain(m.flow_error_typed_io_transcription_failed());
    expect(body).not.toContain(m.flow_run_error_desc());
    expect(body).toContain("Step 1: transcription failed for 'utvecklingssamtal.mp3'.");
  });

  it("prefers a known step error code over an ordinary run error code", () => {
    const { body } = render(FlowRunErrorAlert, {
      props: {
        error: runError({
          code: FLOW_API_ERROR_CODE.RUN_USER_CANCELLED,
          message: "Run cancelled.",
          source: "user_cancel"
        }),
        errorCode: FLOW_API_ERROR_CODE.STEP_EXECUTION_FAILED,
        message: "Step 1 failed."
      }
    });

    expect(body).toContain(m.flow_error_flow_step_execution_failed());
    expect(body).not.toContain(m.flow_error_flow_run_user_cancelled());
  });

  it("falls through from unknown step codes to a known run error code", () => {
    const { body } = render(FlowRunErrorAlert, {
      props: {
        error: runError(),
        errorCode: "provider_timeout",
        message: "Provider timed out."
      }
    });

    expect(body).toContain(m.flow_error_flow_step_execution_failed());
    expect(body).not.toContain(m.flow_run_error_desc());
    expect(body).toContain("Provider timed out.");
  });

  it("keeps review-policy affected-step guidance ahead of the generic catalog message", () => {
    const { body } = render(FlowRunErrorAlert, {
      props: {
        error: runError({
          code: FLOW_API_ERROR_CODE.REVIEW_POLICY_INVALID,
          message: "Review policy is invalid.",
          source: "invalid_flow_definition",
          step_order: 3
        }),
        errorCode: FLOW_API_ERROR_CODE.STEP_EXECUTION_FAILED,
        message: "Review policy is invalid.",
        steps: [
          { step_order: 3, user_description: "Legal review", review_policy: { mode: "view" } }
        ]
      }
    });

    expect(body).toContain(m.flow_run_error_review_policy_invalid_summary());
    expect(body).toContain(m.flow_run_error_review_policy_invalid_action());
    expect(body).toContain("Legal review");
    expect(body).not.toContain(m.flow_error_flow_step_execution_failed());
    expect(body).not.toContain(m.flow_error_flow_review_policy_invalid());
  });
});
