import { EneoError } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import {
  getValidationIssueMessage,
  parseServerValidationIdentity,
  parseValidationError
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
      stepOrder: 3
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
    expect(identity).toEqual({ code: "flow_input_binding_runtime_input_unused", stepOrder: 3 });
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
      "flow_step_invalid"
    ]) {
      expect(getValidationIssueMessage(code)).not.toBe(code);
    }
  });
});
