import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";

import {
  advisoryStepRef,
  advisoryText,
  flowNoteText,
  lintWarningText
} from "./builderAdvisoryText";

const ENGLISH = "Rewired redundant all_previous_steps to previous_step.";

describe("advisoryText", () => {
  it.each([
    ["flow_description_update_required", m.ai_builder_advisory_flow_description_update_required()],
    [
      "input_source_all_previous_rewired",
      m.ai_builder_advisory_input_source_all_previous_rewired()
    ],
    ["source_refs_deduped", m.ai_builder_advisory_source_refs_deduped()],
    ["citation_mode_unsupported", m.flow_validation_msg_citation_mode_unsupported()],
    [
      "terminal_renderer_must_not_consume_review_only_step",
      m.ai_builder_advisory_terminal_renderer_must_not_consume_review_only_step()
    ]
  ])("reads %s in the reader's language", (code, expected) => {
    expect(advisoryText({ code, message: ENGLISH })).toBe(expected);
  });

  it("says a calm generic sentence for a code it does not know, never the server's prose", () => {
    const text = advisoryText({ code: "a_new_server_code", message: ENGLISH });
    expect(text).toBe(m.ai_builder_advisory_generic());
    expect(text).not.toContain(ENGLISH);
  });
});

describe("advisoryStepRef", () => {
  it("reads the step a field-scoped advisory is about", () => {
    expect(advisoryStepRef({ field: "step_b.input_source" })).toBe("step_b");
    expect(advisoryStepRef({ field: "step_b.input_bindings.source_refs" })).toBe("step_b");
  });

  it("names no step for flow-level fields", () => {
    expect(advisoryStepRef({ field: "steps.runtime_input.max_files" })).toBeNull();
    expect(advisoryStepRef({ field: "steps" })).toBeNull();
    expect(advisoryStepRef({ field: "form_fields" })).toBeNull();
    expect(advisoryStepRef({ field: null })).toBeNull();
  });
});

describe("lintWarningText", () => {
  it("names the dropped field when the server says which", () => {
    expect(
      lintWarningText({
        code: "source_contract_shadow_form_field_dropped",
        message: "Runtime field 'diarienummer' was removed.",
        field_name: "diarienummer"
      })
    ).toBe(
      m.ai_builder_lint_source_contract_shadow_form_field_dropped_named({ field: "diarienummer" })
    );
  });

  it("does not mine the field name out of the server's prose", () => {
    expect(
      lintWarningText({
        code: "primary_input_shadow_form_field_dropped",
        message: "Runtime field 'ljudfil' was removed during form-field normalization."
      })
    ).toBe(m.ai_builder_lint_primary_input_shadow_form_field_dropped());
  });

  it("falls back to a translated sentence for an unknown warning", () => {
    const text = lintWarningText({ code: "some_new_check", message: ENGLISH });
    expect(text).toBe(m.ai_builder_lint_generic());
    expect(text).not.toContain(ENGLISH);
  });
});

describe("flowNoteText", () => {
  it("keeps notes about the flow as it already was in calm copy", () => {
    expect(flowNoteText({ code: "vague_step_name" })).toBe(
      m.ai_builder_flow_note_vague_step_name()
    );
    expect(flowNoteText({ code: "unknown_note" })).toBe(m.ai_builder_flow_note_generic());
  });
});
