import { EneoError } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import { securityClassName } from "./flowClassificationNames";
import type { UnattendedToolRefusal } from "./flowToolRefusal";
import {
  describeClassificationRefusal,
  describeToolStepRefusal,
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

describe("tool step refusals", () => {
  const identity = (code: string, context: Record<string, unknown>) =>
    parseServerValidationIdentity({ response: { code, context: { step_order: 3, ...context } } });

  // Kills: two refusal levels, two configuration fields or two argument
  // problems share a sentence; a level, field or problem has none of its own.
  it("gives every refusal level, configuration field and argument problem its own sentence", () => {
    const levels: Record<UnattendedToolRefusal, true> = {
      server_not_found: true,
      server_disabled: true,
      server_not_general: true,
      server_forwards_identity: true,
      tool_not_found: true,
      tool_removed_at_server: true,
      tool_waiting_for_review: true,
      tool_switched_off: true,
      space_is_personal: true,
      server_not_in_space: true,
      tool_switched_off_in_space: true,
      server_below_space_classification: true
    };
    const fields = ["input_type", "output_mode", "input_config.runtime_input", "input_config.tool"];
    const problems = [
      "composed_text",
      "nested_reference",
      "step_not_earlier",
      "unknown_reference",
      "missing_required",
      "outside_schema"
    ];
    const facts = [
      ...Object.keys(levels).map((refusal) => identity("typed_io_tool_not_allowed", { refusal })),
      ...fields.map((field) => identity("typed_io_tool_invalid_config", { field })),
      ...problems.map((problem) =>
        identity("typed_io_tool_invalid_config", { argument: "query", problem })
      )
    ];

    const sentences = facts.flatMap((fact) =>
      fact?.toolRefusal ? [describeToolStepRefusal(fact.toolRefusal)] : []
    );
    expect(new Set(sentences).size).toBe(22);
  });

  // Kills: the invalid-schema refusal, which carries no issue_code, is not
  // routed to its step.
  it("routes the invalid-schema refusal by its code", () => {
    expect(identity("typed_io_tool_invalid_schema", {})).toMatchObject({
      code: "typed_io_tool_invalid_schema",
      stepOrder: 3
    });
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
  const TOOL_WRITE_DOWN = "flow_step_tool_arguments_classification_write_down";

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

  // The organisation's own classes: Eneo ships no fixed names for the levels.
  const classes = [
    { name: "Öppen", security_level: 1 },
    { name: "Intern", security_level: 2 },
    { name: "Konfidentiell", security_level: 3 }
  ];
  const names = {
    stepLabel: (order: number) =>
      ({ 1: "Transkribera", 2: "Sammanfatta" })[order] ?? `Steg ${order}`,
    modelName: (id: string) => ({ "model-a": "Modell A", "model-b": "Modell B" })[id],
    className: (level: number) => securityClassName(classes, level)
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

  it("gives every code a translated fallback for a refusal without facts", () => {
    const fallbacks = [MISMATCH, WRITE_DOWN, TOOL_WRITE_DOWN].map((code) => {
      expect(getValidationIssueMessage(code)).not.toBe(code);
      return getValidationIssueMessage(code);
    });
    expect(new Set(fallbacks).size).toBe(3);
  });

  // Fails when the tool refusal is read as a model refusal (a model picker
  // sentence), loses the unclassified server, or drops the sending sentence.
  it("says which step's data a tool step sends to a server below it", () => {
    const identity = parseServerValidationIdentity(
      refusalError(TOOL_WRITE_DOWN, {
        required_level: 3,
        current_level: null,
        cause: "reads",
        source_step_orders: [1]
      })
    );
    const refusal: ClassificationRefusal = {
      kind: "tool_arguments_write_down",
      requiredLevel: 3,
      currentLevel: null,
      cause: "reads",
      sourceStepOrders: [1],
      qualifyingModelIds: []
    };
    expect(identity?.classification).toEqual(refusal);

    const message = describeClassificationRefusal(refusal, names);

    expect(message).toBe(
      `${m.flow_validation_classification_reads({ name: "Konfidentiell", sources: "Transkribera" })} ${m.flow_error_flow_step_tool_arguments_classification_write_down()}`
    );
  });

  // Fails when a level set by the tool's server is blamed on the space.
  it("names the tool's server when it sets the level a model must clear", () => {
    const identity = parseServerValidationIdentity(
      refusalError(MISMATCH, {
        required_level: 3,
        current_level: 2,
        cause: "external_source",
        source_step_orders: [],
        qualifying_model_ids: ["model-a"]
      })
    );
    const refusal: ClassificationRefusal = {
      kind: "model_below_required",
      requiredLevel: 3,
      currentLevel: 2,
      cause: "external_source",
      sourceStepOrders: [],
      qualifyingModelIds: ["model-a"]
    };
    expect(identity?.classification).toEqual(refusal);

    const message = describeClassificationRefusal(refusal, names);

    expect(message).toContain(
      m.flow_validation_classification_external_source({ name: "Konfidentiell" })
    );
    expect(message).toContain("Modell A");
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

    expect(message).toContain("Konfidentiell");
    expect(message).toContain("Transkribera");
    expect(message).toContain("Intern");
    expect(message).toContain("Modell A");
    expect(message).toContain("Modell B");
    expect(message).not.toContain("undefined");
  });

  it("names a level as the organisation named it, and invents no name for one it has no class for", () => {
    const refusal: ClassificationRefusal = {
      kind: "model_below_required",
      requiredLevel: 3,
      currentLevel: 2,
      cause: "space",
      sourceStepOrders: [],
      qualifyingModelIds: ["model-a"]
    };
    const renamed = describeClassificationRefusal(refusal, {
      ...names,
      className: (level) => securityClassName([{ name: "Sekretess", security_level: 3 }], level)
    });

    expect(renamed).toContain("Sekretess");
    expect(renamed).toContain(m.flow_classification_unnamed_level({ level: "2" }));
    expect(renamed).not.toMatch(/K[0-9]/);
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

    expect(knowledge).toContain("Konfidentiell");
    expect(space).toContain("Konfidentiell");
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

    expect(message).toContain("Intern");
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
    expect(message).toContain("Konfidentiell");
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

    expect(message).toContain("Öppen");
    expect(message).toContain("Konfidentiell");
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

describe("getValidationIssueMessage", () => {
  // Every value of FlowGraphIssueCode (backend/src/eneo/flows/domain/flow_step_validation.py).
  // A code without a sentence reaches the banner as the server's English text.
  const SERVER_ISSUE_CODES = [
    "audio_document_transcript_chain_invalid",
    "citation_mode_unsupported",
    "duplicate_step_name",
    "duplicate_step_order",
    "flow_audio_transcription_invalid",
    "flow_audio_transcription_model_required",
    "flow_audio_transcription_required",
    "flow_has_no_steps",
    "flow_speaker_service_not_chosen",
    "flow_speaker_service_unavailable",
    "flow_http_post_output_must_be_terminal",
    "flow_input_alias_not_received",
    "flow_input_binding_future_step_reference",
    "flow_input_binding_invalid_step_reference",
    "flow_input_binding_unknown_step_order",
    "flow_input_binding_runtime_input_unused",
    "flow_input_binding_unsupported_key",
    "flow_input_contract_inapplicable",
    "flow_review_policy_invalid",
    "flow_review_policy_outbound_output_unsupported",
    "flow_step_invalid",
    "flow_step_limit_exceeded",
    "input_contract_source_mismatch",
    "input_contract_type_mismatch",
    "invalid_input_contract_schema",
    "invalid_output_contract_schema",
    "output_contract_template_fill_incompatible",
    "output_contract_type_mismatch",
    "step_order_not_contiguous",
    "template_fill_requires_docx",
    "transcribe_only_violation",
    "typed_io_audio_source_unsupported",
    "typed_io_document_source_unsupported",
    "typed_io_file_source_unsupported",
    "typed_io_flow_input_position_invalid",
    "typed_io_incompatible_type_chain",
    "typed_io_invalid_input_source_combination",
    "typed_io_invalid_input_source_position",
    "typed_io_missing_previous_step",
    "typed_io_multiple_flow_input_steps",
    "unsupported_input_type"
  ];

  it.each(SERVER_ISSUE_CODES)("has a sentence for the server code %s", (code) => {
    expect(getValidationIssueMessage(code)).not.toBe(code);
  });

  it("has a sentence for a step that calls a service without an address", () => {
    expect(getValidationIssueMessage("http_missing_url")).toBe(
      m.flow_validation_msg_http_missing_url()
    );
  });
});
