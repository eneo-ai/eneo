import { createTranslator } from "use-intl";
import { describe, expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { EneoApiError } from "@/lib/api/errors";
import { FlowEditorError } from "./editor-api";
import {
  anchorForPath,
  describeSaveError,
  isStaleRevision,
  type Translator
} from "./field-problems";

const t = createTranslator({ locale: "sv", messages }) as unknown as Translator;

function refusal(code: string, context: Record<string, unknown> = {}, status = 400) {
  return new FlowEditorError(new EneoApiError("English text", { status, reason: code }), context);
}

const step = {
  stepId: "step-2",
  stepOrder: 2,
  config: { input_source: "http_get", output_mode: "pass_through" } as const
};

describe("anchorForPath", () => {
  it("puts a credential of a fetching step at its HTTP settings", () => {
    expect(anchorForPath("input_config.auth.token", step.config)).toBe("input_config.http");
    expect(anchorForPath("input_config.tool.arguments.q", step.config)).toBe("input_config.tool");
    expect(anchorForPath("input_bindings.question", step.config)).toBe("input_bindings");
    expect(
      anchorForPath("output_config.bindings", {
        input_source: "flow_input",
        output_mode: "template_fill"
      })
    ).toBe("output_config.template");
  });
});

describe("describeSaveError", () => {
  it("shows a refusal at the field its context names, in the reader's words", () => {
    const problem = describeSaveError(
      refusal("typed_io_http_invalid_config", { field: "input_config.url", step_order: 2 }),
      step,
      t
    );
    expect(problem.anchor).toBe("input_config.http");
    expect(problem.message).toBe(messages.flow_error_typed_io_http_invalid_config);
    expect(problem.message).not.toContain("English");
  });

  it("names the field of a code without a field in its context", () => {
    expect(
      describeSaveError(refusal("flow_step_security_classification_mismatch"), step, t).anchor
    ).toBe("completion_model");
    expect(
      describeSaveError(
        refusal("flow_step_invalid", { issue_code: "typed_io_incompatible_type_chain" }),
        step,
        t
      )
    ).toMatchObject({
      anchor: "input_type",
      message: messages.flow_validation_msg_incompatible_type_chain
    });
  });

  it("shows another step's problem with the form, naming that step", () => {
    const problem = describeSaveError(
      refusal("flow_step_read_lost_producer", { step_order: 3 }),
      step,
      t
    );
    expect(problem).toMatchObject({ anchor: null, otherStepOrder: 3 });
  });

  it("places a request validation error at the step field it names", () => {
    const error = new FlowEditorError(
      new EneoApiError("Request validation failed", {
        status: 422,
        reason: "request_validation_error",
        details: {
          errors: [{ location: "body.step_edits.0.changes.timeout_seconds", message: "x" }]
        }
      }),
      {}
    );
    expect(describeSaveError(error, step, t)).toMatchObject({
      anchor: "timeout_seconds",
      message: messages.flow_step_editor_value_invalid
    });
  });

  it("recognises a stale revision", () => {
    expect(isStaleRevision(refusal("stale_revision"))).toBe(true);
    expect(isStaleRevision(new Error("x"))).toBe(false);
  });
});
