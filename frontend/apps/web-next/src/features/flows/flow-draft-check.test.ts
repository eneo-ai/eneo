import { describe, expect, it } from "vitest";
import { makeAssistant } from "./editor/testing/fixtures";
import { checkDraft, problemCount, type DraftFacts } from "./flow-draft-check";
import { makeFlow, makeStep } from "./flow-fixtures";

const none: DraftFacts = {
  assistants: new Map(),
  toolOptions: null,
  classification: null,
  speakerServices: []
};

describe("checkDraft", () => {
  it("finds nothing in a draft the core would publish", () => {
    const flow = makeFlow();
    expect(checkDraft(flow, none)).toEqual({ flow: [], steps: [] });
  });

  it("says a draft without steps cannot be published", () => {
    expect(checkDraft(makeFlow({ steps: [] }), none).flow).toEqual([{ code: "no_steps" }]);
  });

  it("names, per step, the settings publishing needs", () => {
    const flow = makeFlow({
      steps: [
        makeStep(1, {
          input_source: "http_get",
          input_config: { url: " ", auth: { mode: "none" } }
        }),
        makeStep(2, {
          output_mode: "template_fill",
          output_type: "docx",
          output_config: {
            template_asset_id: "t-1",
            placeholders: ["namn", "datum"],
            bindings: { namn: "{{step_1.output.text}}", gammal: "x" }
          }
        }),
        makeStep(3, { user_description: " ", input_source: "tool", input_config: {} })
      ]
    });
    const check = checkDraft(flow, none);
    expect(check.steps.map(({ step, problems }) => [step.step_order, problems])).toEqual([
      [1, [{ code: "http_url_missing" }]],
      [2, [{ code: "template_unbound" }, { code: "template_orphaned" }]],
      [3, [{ code: "name_missing" }, { code: "tool_missing" }]]
    ]);
    expect(problemCount(check)).toBe(5);
  });

  it("judges with what the core answered: models, tools and the classification", () => {
    const flow = makeFlow({
      steps: [
        makeStep(1, {
          input_source: "tool",
          input_config: { tool: { mcp_server_id: "s-1", tool_id: "search", arguments: {} } }
        }),
        makeStep(2)
      ]
    });
    const check = checkDraft(flow, {
      assistants: new Map([
        ["assistant-2", makeAssistant({ id: "assistant-2", completion_model: null })]
      ]),
      toolOptions: [
        {
          mcp_server_id: "s-1",
          mcp_server_name: "Arkiv",
          mcp_server_security_level: null,
          tool_id: "search",
          tool_name: "Sök",
          tool_description: null,
          refusal: null,
          input_schema: { properties: { query: { type: "string" } }, required: ["query"] }
        }
      ],
      classification: [
        {
          step_id: "step-2",
          step_order: 2,
          input_level: 2,
          reads: [1],
          knowledge_level: null,
          external_source_level: null,
          model_level: null,
          required_model_level: 2,
          qualifying_model_ids: [],
          effective_output_level: 2,
          output_floor: null,
          violation: {
            cause: "input",
            code: "flow_step_security_classification_mismatch",
            current_level: 1,
            message: "Below.",
            required_level: 2,
            source_step_orders: [1]
          }
        }
      ] as never,
      speakerServices: []
    });
    expect(check.steps.map(({ problems }) => problems.map((problem) => problem.code))).toEqual([
      ["tool_arguments_missing"],
      ["model_missing", "classification"]
    ]);
  });

  it("finds a read of a removed step in the underlag, the tool arguments and the prompt", () => {
    const flow = makeFlow({
      steps: [
        makeStep(1, {
          input_bindings: { source_refs: [{ step_ref: "step_3_deleted", output: "text" }] }
        }),
        makeStep(2, {
          input_source: "tool",
          input_config: {
            tool: { mcp_server_id: "s-1", tool_id: "t", arguments: { q: "{{ step_3_deleted }}" } }
          }
        }),
        makeStep(3)
      ]
    });
    const check = checkDraft(flow, {
      ...none,
      assistants: new Map([
        [
          "assistant-3",
          makeAssistant({
            id: "assistant-3",
            prompt: { text: "Läs {{step_4_deleted.output.text}}", description: null }
          } as never)
        ]
      ])
    });
    expect(
      check.steps.map(({ step, problems }) => [
        step.step_order,
        problems.some((problem) => problem.code === "deleted_reference")
      ])
    ).toEqual([
      [1, true],
      [2, true],
      [3, true]
    ]);
  });

  it("asks an audio flow for its transcription model and the service its speakers need", () => {
    const flow = makeFlow({
      steps: [
        makeStep(1, { input_type: "audio", output_mode: "transcribe_only" }),
        makeStep(2, {
          output_mode: "speaker_mapping",
          output_type: "json",
          output_config: {
            speaker_mapping: { infer_names: true }
          }
        })
      ],
      metadata_json: { wizard: { transcription_enabled: true } }
    });
    expect(checkDraft(flow, none).flow).toEqual([
      { code: "transcription_model_missing" },
      { code: "speaker_service_missing" }
    ]);
  });
});
