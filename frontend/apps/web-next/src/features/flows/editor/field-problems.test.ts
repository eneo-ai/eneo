import { describe, expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { EneoApiError } from "@/lib/api/errors";
import { testTranslator } from "@/test/i18n";
import { FlowEditorError } from "./editor-api";
import {
  anchorForPath,
  describeSaveError,
  isStaleRevision,
  refusalAnchor,
  refusalMessage,
  type Translator
} from "./field-problems";

const t = testTranslator() as unknown as Translator;

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
    expect(anchorForPath("input_config.auth.token", step.config)).toBe("input_config.http.auth");
    expect(anchorForPath("input_config.url", step.config)).toBe("input_config.http");
    expect(anchorForPath("input_config.custom_headers[0].value", step.config)).toBe(
      "input_config.http.more"
    );
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

describe("anchorForPath for a deliverable", () => {
  it("puts a refused label or file name at its own field, also on a Word template step", () => {
    for (const output_mode of ["template_fill", "render_verbatim"] as const) {
      const config = { input_source: "previous_step", output_mode } as const;
      expect(anchorForPath("output_config.deliverable.file_name", config)).toBe(
        "output_config.deliverable.file_name"
      );
      expect(anchorForPath("output_config.deliverable.label", config)).toBe(
        "output_config.deliverable.label"
      );
      expect(anchorForPath("output_config.deliverable", config)).toBe(
        "output_config.deliverable.label"
      );
    }
  });
});

describe("refusalAnchor", () => {
  it("opens a publish refusal where the editor shows its field, then its code's field", () => {
    expect(refusalAnchor({ field: "prompt", reference: "datun" }, "x", step.config)).toBe("prompt");
    expect(
      refusalAnchor({ field: "input_config", http_error: "HTTP_MISSING_AUTH" }, "x", step.config)
    ).toBe("input_config.http.auth");
    // A field given by the caller (a lost read's site) wins over the context's.
    expect(refusalAnchor({}, "x", step.config, "input_bindings.question")).toBe("input_bindings");
    expect(
      refusalAnchor(
        { issue_code: "typed_io_incompatible_type_chain" },
        "flow_step_invalid",
        step.config
      )
    ).toBe("input_type");
    expect(refusalAnchor({}, "something_new", step.config)).toBeNull();
  });

  it("gives a refusal's sentence the values it names", () => {
    const sentence = testTranslator("sv", {
      flow_validation_msg_template_binding_not_scalar: "Fältet {placeholder} tar ett värde."
    }) as unknown as Translator;
    expect(
      refusalMessage("template_binding_not_scalar", sentence, { placeholder: "Deltagare" })
    ).toBe("Fältet Deltagare tar ett värde.");
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

  it("says which HTTP setting to change when the core names the defect", () => {
    const problem = describeSaveError(
      refusal("typed_io_http_invalid_config", {
        field: "input_config",
        http_error: "HTTP_CREDENTIALS_REQUIRE_HTTPS",
        issue_code: "flow_step_invalid",
        step_order: 2
      }),
      step,
      t
    );
    expect(problem.anchor).toBe("input_config.http");
    expect(problem.message).toBe(messages.flow_step_editor_http_credentials_need_https);
  });

  it("shows an HTTP defect at the part it is about, not at the address", () => {
    const sending = {
      stepId: "step-2",
      stepOrder: 2,
      config: { input_source: "previous_step", output_mode: "http_post" } as const
    };
    const at = (httpError: string) =>
      describeSaveError(
        refusal("typed_io_http_invalid_config", {
          field: "output_config",
          http_error: httpError,
          step_order: 2
        }),
        sending,
        t
      ).anchor;
    expect(at("HTTP_INVALID_BODY_JSON")).toBe("output_config.http.body");
    expect(at("HTTP_MISSING_AUTH")).toBe("output_config.http.auth");
    expect(at("HTTP_TIMEOUT_OUT_OF_RANGE")).toBe("output_config.http.more");
    expect(at("HTTP_INVALID_HEADER_NAME")).toBe("output_config.http.more");
    // The core names the header; an API key's header name is a sign-in setting.
    const header = (field: string) =>
      describeSaveError(
        refusal("typed_io_http_invalid_config", {
          field,
          http_error: "HTTP_INVALID_HEADER_NAME",
          step_order: 2
        }),
        sending,
        t
      );
    expect(header("output_config.custom_headers[1]").anchor).toBe("output_config.http.more");
    expect(header("output_config.custom_headers[1]").message).toBe(
      messages.flow_step_editor_http_header_name_invalid
    );
    expect(header("output_config.auth.header_name").anchor).toBe("output_config.http.auth");
    expect(at("HTTP_INVALID_URL")).toBe("output_config.http");
    // A fetching step has no body field: the address is where it is shown.
    expect(
      describeSaveError(
        refusal("typed_io_http_invalid_config", {
          field: "input_config",
          http_error: "HTTP_BODY_NOT_ALLOWED_FOR_GET",
          step_order: 2
        }),
        step,
        t
      ).anchor
    ).toBe("input_config.http");
  });

  it("shows a refused body that sends the run's result at the field the core names", () => {
    const sending = {
      stepId: "step-3",
      stepOrder: 3,
      config: { input_source: "previous_step", output_mode: "http_post" } as const
    };
    // The contexts the core raises (`test_validator.py`, the run result body's field and advice).
    const at = (field: string, httpError: string) =>
      describeSaveError(
        refusal("typed_io_http_invalid_config", { field, http_error: httpError }),
        sending,
        t
      );
    const url = at("output_config.url", "HTTP_RUN_RESULT_REQUIRES_FIXED_HTTPS_URL");
    expect(url.anchor).toBe("output_config.http");
    expect(url.message).toBe(messages.flow_step_editor_http_run_result_url_fixed);
    const header = at("output_config.custom_headers[1]", "HTTP_CONTENT_TYPE_SET_BY_BODY");
    expect(header.anchor).toBe("output_config.http.more");
    expect(header.message).toBe(messages.flow_step_editor_http_run_result_content_type);
    expect(at("output_config.auth.header_name", "HTTP_CONTENT_TYPE_SET_BY_BODY").anchor).toBe(
      "output_config.http.auth"
    );
    const template = at("output_config.body.template", "HTTP_RUN_RESULT_TAKES_NO_TEMPLATE");
    expect(template.anchor).toBe("output_config.http.body");
    expect(template.message).toBe(messages.flow_step_editor_http_run_result_no_template);
  });

  it("keeps the https rule of the step that sends the run's result to the core's code for it", () => {
    // The step as the editor passes it: its whole draft, output included.
    const sending = {
      input_source: "previous_step",
      output_mode: "http_post",
      output_config: { url: "https://a..b.example/in", body: { mode: "run_result" } }
    } as const;
    const at = (context: Record<string, unknown>) =>
      describeSaveError(
        refusal("typed_io_http_invalid_config", context),
        { stepId: "", stepOrder: 2, config: sending },
        t
      );
    // What the core answers a save of the step that sends the run's result whose
    // host it refuses (`https://a..b.example/in`, `draft_step_refusals`): no `http_error`.
    const host = at({ field: "output_config.url", issue_code: "flow_step_invalid", step_order: 2 });
    expect(host.anchor).toBe("output_config.http");
    expect(host.message).toBe(messages.flow_validation_msg_flow_step_invalid);
    // Another address code keeps the text it has for any step.
    expect(at({ field: "output_config", http_error: "HTTP_INVALID_URL" }).message).toBe(
      messages.flow_step_editor_http_url_invalid
    );
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
