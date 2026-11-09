import { describe, expect, it } from "vitest";
import { makeAssistant } from "./editor/testing/fixtures";
import { checkDraft, problemAnchor, problemCount, type DraftFacts } from "./flow-draft-check";
import { makeFlow, makeStep } from "./flow-fixtures";

const none: DraftFacts = {
  assistants: new Map(),
  toolOptions: null,
  classification: null,
  transcription: { models: [], services: [] }
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
      [1, [{ code: "http_url_missing", anchor: "input_config.http" }]],
      [2, [{ code: "template_unbound" }, { code: "template_orphaned" }]],
      [3, [{ code: "name_missing" }, { code: "tool_missing" }]]
    ]);
    expect(problemCount(check)).toBe(5);
  });

  it("says a connection still waits for its credential", () => {
    const flow = makeFlow({
      steps: [
        makeStep(1, {
          input_source: "http_get",
          input_config: {
            url: "https://api.example.se/cases",
            auth: { mode: "api_key", header_name: "X-API-Key", key: "" }
          }
        }),
        makeStep(2, {
          output_mode: "http_post",
          output_config: {
            url: "https://hooks.example.se/in",
            auth: { mode: "bearer_token", token: { $secret: "stored" } }
          }
        })
      ]
    });
    expect(
      checkDraft(flow, none).steps.map(({ step, problems }) => [step.step_order, problems])
    ).toEqual([[1, [{ code: "http_credential_missing", anchor: "input_config.http" }]]]);
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
      transcription: { models: [], services: [] }
    });
    expect(check.steps.map(({ problems }) => problems.map((problem) => problem.code))).toEqual([
      ["tool_arguments_missing"],
      ["model_missing", "classification"]
    ]);
  });

  it("blocks an AI step without an instruction, as the editor warns, but not a speaker step", () => {
    const flow = makeFlow({
      steps: [makeStep(1), makeStep(2, { output_mode: "speaker_mapping", output_type: "json" })]
    });
    const blank = (id: string) =>
      makeAssistant({ id, prompt: { text: "  ", description: null } } as never);
    const check = checkDraft(flow, {
      ...none,
      assistants: new Map([
        ["assistant-1", blank("assistant-1")],
        ["assistant-2", blank("assistant-2")]
      ])
    });
    const first = check.steps.find(({ step }) => step.step_order === 1)?.problems ?? [];
    expect(first).toEqual([{ code: "prompt_missing" }]);
    expect(problemAnchor(first[0]!)).toBe("prompt");
    expect(
      check.steps
        .find(({ step }) => step.step_order === 2)
        ?.problems.some((problem) => problem.code === "prompt_missing") ?? false
    ).toBe(false);
  });

  it("counts a Word field filled from a source the flow no longer has as unfilled", () => {
    const template = (bindings: Record<string, string>) =>
      makeFlow({
        metadata_json: {
          form_schema: { fields: [{ name: "namn", label: "Namn", type: "text" }] }
        },
        steps: [
          makeStep(1, {
            output_mode: "template_fill",
            output_type: "docx",
            output_config: { template_asset_id: "t-1", placeholders: ["namn", "datum"], bindings }
          })
        ]
      });
    const codes = (bindings: Record<string, string>) =>
      checkDraft(template(bindings), none).steps.flatMap(({ problems }) =>
        problems.map((problem) => problem.code)
      );
    expect(codes({ namn: "{{flow_input.namn}}", datum: "{{datum}}" })).toEqual([]);
    expect(codes({ namn: "{{flow_input.arende}}", datum: "" })).toEqual(["template_unbound"]);
  });

  it("reads a Word field's binding as the run does, not as the picker writes it", () => {
    const codes = (binding: string) =>
      checkDraft(
        makeFlow({
          steps: [
            makeStep(1, { user_description: "Beslut" }),
            makeStep(2, {
              output_mode: "template_fill",
              output_type: "docx",
              output_config: {
                template_asset_id: "t-1",
                placeholders: ["innehall"],
                bindings: { innehall: binding }
              }
            })
          ]
        }),
        none
      )
        .steps.find(({ step }) => step.step_order === 2)
        ?.problems.map((problem) => problem.code) ?? [];
    // Spaces inside the braces, the previous step's alias and the run's text input all read a value.
    for (const binding of [
      "{{ datum }}",
      " {{ step_1.output.text }} ",
      "{{föregående_steg}}",
      "{{flow_input.text}}"
    ]) {
      expect(codes(binding), binding).toEqual([]);
    }
    // A step that is gone, or that is not earlier, fills nothing.
    expect(codes("{{step_9.output.text}}")).toEqual(["template_unbound"]);
    expect(codes("{{ step_2.output.text }}")).toEqual(["template_unbound"]);
  });

  it("opens each problem at the field that fixes it", () => {
    expect(problemAnchor({ code: "template_missing" })).toBe("output_config.template");
    expect(problemAnchor({ code: "model_missing" })).toBe("completion_model");
    expect(problemAnchor({ code: "tool_missing" })).toBe("input_config.tool");
    expect(problemAnchor({ code: "name_missing" })).toBe("user_description");
    expect(problemAnchor({ code: "http_url_missing", anchor: "output_config.http" })).toBe(
      "output_config.http"
    );
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
        problems.flatMap((problem) =>
          problem.code === "deleted_reference" ? [problemAnchor(problem)] : []
        )
      ])
    ).toEqual([
      [1, ["input_bindings"]],
      [2, ["input_config.tool"]],
      [3, ["prompt"]]
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

  it("asks for another live model when the space can no longer stream through the chosen one", () => {
    const whisper = { id: "whisper", name: "kb-whisper-large", supports_realtime: false };
    const live = { id: "live", name: "pianissimo-sv-live", supports_realtime: true };
    const flow = makeFlow({
      steps: [makeStep(1, { input_type: "audio", output_mode: "transcribe_only" })],
      metadata_json: {
        wizard: {
          transcription_enabled: true,
          transcription_model: { id: "whisper" },
          transcription_speaker_service: null,
          transcription_live_model: { id: "live" }
        }
      }
    });
    const offering = (models: (typeof whisper)[]) => ({
      ...none,
      transcription: { models, services: [] }
    });

    expect(checkDraft(flow, offering([whisper, live])).flow).toEqual([]);
    expect(checkDraft(flow, offering([whisper])).flow).toEqual([
      { code: "live_model_unavailable" }
    ]);
    expect(
      checkDraft(flow, offering([whisper, { ...live, supports_realtime: false }])).flow
    ).toEqual([{ code: "live_model_unavailable" }]);
  });
});
