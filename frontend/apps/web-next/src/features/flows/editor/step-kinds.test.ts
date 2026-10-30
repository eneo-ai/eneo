import { createTranslator } from "use-intl";
import { describe, expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import type { Translator } from "./field-problems";
import { kindRefusalText, newStepUpdate, uniqueStepName } from "./step-kinds";
import { makeFlow, makeKindOption, makeKindRefusal, makeStep } from "./testing/fixtures";

const t = createTranslator({ locale: "sv", messages }) as unknown as Translator;

const OPTIONS = {
  name: "  Nytt steg ",
  url: "https://api.example.org/arenden",
  tool: { mcp_server_id: "server-1", tool_id: "tool-1", arguments: {} }
};

const twoSteps = makeFlow({
  steps: [
    makeStep({ output_type: "json" }),
    makeStep({
      id: "step-2",
      assistant_id: "assistant-2",
      step_order: 2,
      user_description: "Skriv svar",
      input_source: "previous_step",
      input_type: "json"
    })
  ]
});

describe("newStepUpdate", () => {
  it("adds the core's configuration among every saved step, fenced on the read revision", () => {
    const option = makeKindOption("ai", { configuration: { input_type: "json" } });
    expect(newStepUpdate(twoSteps, 2, option, OPTIONS)).toEqual({
      expected_revision: 4,
      definition: {},
      new_steps: [{ name: "Nytt steg", configuration: option.configuration, assistant: {} }],
      step_order: [{ step_id: "step-1" }, { new_step: 0 }, { step_id: "step-2" }]
    });
  });

  it("makes the saved steps' changes the core gives, and puts the chosen format in", () => {
    const flow = makeFlow({ steps: [makeStep({ input_type: "json" })] });
    const handOver = { step_id: "step-1", changes: { input_source: "previous_step" } };
    const option = makeKindOption("document", {
      configuration: {
        input_source: "flow_input",
        output_mode: "render_verbatim",
        output_type: "docx"
      },
      step_edits: [handOver]
    });
    const update = newStepUpdate(flow, 1, option, { ...OPTIONS, format: "pdf" });
    expect(update.new_steps?.[0]?.configuration).toMatchObject({
      input_source: "flow_input",
      output_mode: "render_verbatim",
      output_type: "pdf"
    });
    expect(update.step_order).toEqual([{ new_step: 0 }, { step_id: "step-1" }]);
    expect(update.step_edits).toEqual([handOver]);
  });

  it("turns transcription on when the core says the step needs it", () => {
    const option = makeKindOption("transcribe", { turns_on_transcription: true });
    const update = newStepUpdate(makeFlow({ steps: [] }), 1, option, OPTIONS);
    expect(update.definition).toEqual({
      metadata_json: { wizard: { transcription_enabled: true } }
    });
  });

  it("puts the entered address and tool into the core's request settings", () => {
    const http = { url: "", auth: { mode: "none" }, timeout_seconds: 30 };
    const fetch = makeKindOption("fetch_http", {
      configuration: { input_source: "http_get", input_config: http }
    });
    const send = makeKindOption("send_http", {
      configuration: { output_mode: "http_post", output_config: http }
    });
    const tool = makeKindOption("tool", { configuration: { input_source: "tool" } });
    const configurationOf = (option: typeof fetch) =>
      newStepUpdate(twoSteps, 3, option, OPTIONS).new_steps?.[0]?.configuration;

    expect(configurationOf(fetch)?.input_config).toEqual({ ...http, url: OPTIONS.url });
    expect(configurationOf(send)?.output_config).toEqual({ ...http, url: OPTIONS.url });
    expect(configurationOf(tool)?.input_config).toEqual({ tool: OPTIONS.tool });
  });
});

describe("kindRefusalText", () => {
  const text = (refusal: Parameters<typeof makeKindRefusal>[0], position = 2) =>
    kindRefusalText(makeKindRefusal(refusal), position, twoSteps, t);
  const terminal = "flow_http_post_output_must_be_terminal";
  const cases: [string, Parameters<typeof makeKindRefusal>[0], number, string][] = [
    [
      "a step that sends over HTTP before another",
      { issue_code: terminal, step_order: 2 },
      2,
      messages.flow_step_editor_kind_block_must_be_last
    ],
    [
      "a step after one that sends over HTTP",
      { issue_code: terminal, step_order: 2, step_id: "step-2" },
      3,
      messages.flow_step_editor_kind_block_after_outbound_step
    ],
    [
      "an answer the step after cannot read",
      { issue_code: "typed_io_incompatible_type_chain", step_order: 3, step_id: "step-2" },
      2,
      messages.flow_step_editor_kind_block_next_step_cannot_read
    ],
    [
      "a step that reads the run's input after step 1",
      { issue_code: "typed_io_flow_input_position_invalid", step_order: 2 },
      2,
      messages.flow_step_editor_kind_block_first_only
    ],
    [
      "a step that needs one before it",
      { issue_code: "typed_io_missing_previous_step", step_order: 1 },
      1,
      messages.flow_step_editor_kind_block_needs_step_before
    ],
    [
      "a step before the one that takes uploads",
      { issue_code: "typed_io_audio_source_unsupported", step_order: 2, step_id: "step-1" },
      1,
      messages.flow_step_editor_kind_block_first_step_takes_uploads
    ]
  ];
  for (const [label, refusal, position, expected] of cases) {
    it(`says so for ${label}`, () => expect(text(refusal, position)).toBe(expected));
  }

  it("names another step a refusal is about, with the catalog's sentence", () => {
    const message = text({
      code: "flow_review_policy_outbound_output_unsupported",
      issue_code: "flow_review_policy_outbound_output_unsupported",
      step_order: 4,
      step_id: "step-2"
    });
    expect(message).toContain("Steg 2: Skriv svar");
    expect(message).toContain(messages.flow_validation_msg_review_policy_outbound_unsupported);
  });

  it("falls back to the flow error catalog, then to a plain refusal", () => {
    expect(text({ code: "flow_unpublish_required", issue_code: null, step_order: null })).toBe(
      messages.flow_error_flow_unpublish_required
    );
    expect(text({ code: "something_new", issue_code: null, step_order: 2 })).toBe(
      messages.flow_step_editor_kind_block_refused
    );
  });
});

it("numbers a default name another step already has", () => {
  expect(uniqueStepName(twoSteps, "Sammanfatta")).toBe("Sammanfatta 2");
  expect(uniqueStepName(twoSteps, "Granskning")).toBe("Granskning");
});
