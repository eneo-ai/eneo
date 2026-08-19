import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import type { Space } from "@eneo/eneo-js";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import type {
  AIBuilderError,
  AIBuilderSession,
  AIBuilderTelemetrySummary,
  ProposedPlan,
  StepSpec
} from "./protocol";
import type { AIBuilderClientTransport } from "./FlowAIBuilderDriver";
import BuilderReviewScreenHarness from "./test-harnesses/BuilderReviewScreenHarness.svelte";

afterEach(() => {
  cleanup();
});

describe("BuilderReviewScreen approval", () => {
  it("offers one primary action in create mode and creates only after the dialog", async () => {
    const createFlowFromPlan = vi.fn().mockResolvedValue({
      flow_id: "flow-1",
      flow_name: "Ljud till PDF",
      steps_created: 2,
      steps_updated: 0,
      steps_removed: 0
    });
    const onapplied = vi.fn();

    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: makeCreateState(),
      screenProps: { onapplied },
      onservice: (service) => {
        service.createFlowFromPlan = createFlowFromPlan;
      }
    });

    expect(screen.queryByRole("button", { name: m.ai_builder_apply() })).toBeNull();
    expect(screen.queryByRole("button", { name: m.ai_builder_approve() })).toBeNull();
    const approve = screen.getAllByRole("button", { name: m.ai_builder_approve_create() });
    expect(approve).toHaveLength(1);

    await fireEvent.click(approve[0]);
    expect(await screen.findByText(m.ai_builder_approve_dialog_title())).toBeTruthy();
    expect(createFlowFromPlan).not.toHaveBeenCalled();

    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_approve_dialog_confirm() })
    );
    await waitFor(() => expect(createFlowFromPlan).toHaveBeenCalledOnce());
    await waitFor(() => expect(onapplied).toHaveBeenCalledOnce());
  });

  it("keeps approve then apply as two steps in edit mode", async () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({ status: "awaiting_approval" }),
        currentPlan: makePlan({ status: "proposed" })
      }
    });
    expect(screen.getByRole("button", { name: m.ai_builder_approve() })).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.ai_builder_apply() })).toBeNull();
    expect(screen.queryByRole("button", { name: m.ai_builder_approve_create() })).toBeNull();
    cleanup();

    const applyPlan = vi.fn().mockResolvedValue({
      flow_id: "flow-1",
      flow_name: "Flöde",
      steps_created: 0,
      steps_updated: 1,
      steps_removed: 0
    });
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({ status: "awaiting_approval" }),
        currentPlan: makePlan({ status: "approved" })
      },
      onservice: (service) => {
        service.applyPlan = applyPlan;
      }
    });

    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_apply() }));
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_approve_dialog_confirm_edit() })
    );
    await waitFor(() => expect(applyPlan).toHaveBeenCalledOnce());
  });

  it("makes no persistence claim and blocks mutation on an unknown create outcome", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        ...makeCreateState(),
        applyError: makeError("unknown"),
        createFailureOutcome: "unknown"
      }
    });

    expect(screen.getByText(m.ai_builder_create_unknown_title())).toBeTruthy();
    expect(screen.queryByText(m.ai_builder_create_failed_body())).toBeNull();
    expect(screen.queryByText(m.ai_builder_plan_unchanged())).toBeNull();
    expect(
      screen.getByRole("button", { name: m.ai_builder_turn_retry() }).hasAttribute("disabled")
    ).toBe(true);
    expect(
      screen.getByRole("button", { name: m.ai_builder_modify() }).hasAttribute("disabled")
    ).toBe(true);
  });

  it("blocks creating an audio plan without an accessible transcription model", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: false }] }),
      state: makeCreateState()
    });

    expect(screen.getByText(m.ai_builder_missing_transcription_model_title())).toBeTruthy();
    expect(
      screen.getByRole("button", { name: m.ai_builder_approve_create() }).hasAttribute("disabled")
    ).toBe(true);
  });
});

describe("BuilderReviewScreen plan document", () => {
  it("shows cumulative planning token usage in the header with details on demand", async () => {
    const state = makeCreateState();
    state.session.telemetry = {
      planner_request_count: 2,
      clarification_question_count: 1,
      prompt_tokens_total: 18_705,
      completion_tokens_total: 6_395,
      total_tokens_total: 25_100,
      tool_call_count_total: 2,
      auxiliary_llm_call_count: 0,
      architecture_commit_count: 1,
      repair_attempts_total: 0,
      parse_repair_attempts_total: 0,
      wall_clock_ms_total: 12_000,
      llm_calls_made_total: 2,
      token_usage_estimated: false,
      last_request_id: "request-2",
      last_model: "openai/gpt-5.6-luna",
      last_finish_reason: "tool_calls",
      last_outcome_kind: "dispatched",
      last_token_usage_source: "provider",
      last_token_usage_estimated: false
    };
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state
    });

    const badge = screen.getByRole("button", { name: /25.100 tokens/ });
    await fireEvent.click(badge);

    expect(await screen.findByText(m.flow_run_token_usage_title())).toBeTruthy();
    expect(screen.getByText(/18.705/)).toBeTruthy();
    expect(screen.getByText(/6.395/)).toBeTruthy();
    expect(screen.getByText(m.ai_builder_token_usage_provider_note())).toBeTruthy();
  });

  it("marks review checkpoints, per-file steps and artifacts from the plan spec", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: makeCreateState()
    });

    expect(screen.getAllByText(m.ai_builder_node_review_checkpoint()).length).toBeGreaterThan(0);
    expect(screen.getAllByText(m.ai_builder_node_per_file()).length).toBeGreaterThan(0);
    expect(screen.getAllByText(m.flow_output_type_pdf()).length).toBeGreaterThan(0);
    expect(screen.getByText(m.ai_builder_review_checkpoint_note({ count: 1 }))).toBeTruthy();
  });

  it("keeps an expanded step expanded across Diagram↔Detaljer switches", async () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: makeCreateState()
    });

    const detailsTab = screen.getByRole("tab", { name: m.ai_builder_canvas_tab_details() });
    await fireEvent.click(detailsTab);
    await waitFor(() => expect(detailsTab.getAttribute("data-state")).toBe("active"));

    const trigger = () =>
      screen.getByRole("button", {
        name: `${m.ai_builder_step_label({ step: 1 })}: Transkribera ljud`
      });
    await fireEvent.click(trigger());
    await waitFor(() => expect(trigger().getAttribute("aria-expanded")).toBe("true"));

    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_diagram() }));
    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_details() }));
    await waitFor(() => expect(trigger().getAttribute("aria-expanded")).toBe("true"));
  });
});

describe("BuilderReviewScreen change requests", () => {
  it("scopes the change box to a step and sends that step's edit context", async () => {
    const sendMessage = vi.fn().mockResolvedValue("delivered");
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: makeCreateState(),
      onservice: (service) => {
        service.sendMessage = sendMessage;
      }
    });

    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_details() }));
    await fireEvent.click(
      screen.getByRole("button", {
        name: `${m.ai_builder_step_label({ step: 2 })}: Rendera PDF`
      })
    );
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_step_request_change({ step: 2 }) })
    );

    expect(
      await screen.findByText(m.ai_builder_change_request_scope({ step: 2, name: "Rendera PDF" }))
    ).toBeTruthy();

    const textarea = screen.getByLabelText(m.ai_builder_change_request_textarea_label());
    await fireEvent.input(textarea, { target: { value: "Lägg till en försättssida" } });
    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_send() }));

    expect(sendMessage).toHaveBeenCalledWith("Lägg till en försättssida", undefined, undefined, {
      kind: "proposed_plan",
      scope: "step",
      plan_id: "plan-1",
      target_plan_step_ref: "step_b",
      target_existing_step_ref: null,
      target_step_name: "Rendera PDF",
      target_step_number: 2
    });
  });

  it("locks approval and shows the overlay while a revision streams", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: { ...makeCreateState(), streamState: "streaming" }
    });

    expect(screen.getByText(m.ai_builder_revising_overlay())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_footer_locked_while_revising())).toBeTruthy();
    expect(
      screen.getByRole("button", { name: m.ai_builder_approve_create() }).hasAttribute("disabled")
    ).toBe(true);
  });

  it("keeps the plan and shows a dismissible notice when the reply carried no new plan", async () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        ...makeCreateState(),
        reviewNote: "Jag kan inte byta modell åt dig — det gör du i stegredigeraren."
      }
    });

    expect(screen.getByRole("heading", { name: "Ljud till PDF" })).toBeTruthy();
    expect(
      screen.getByText("Jag kan inte byta modell åt dig — det gör du i stegredigeraren.")
    ).toBeTruthy();

    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_review_note_acknowledge() })
    );
    await waitFor(() =>
      expect(
        screen.queryByText("Jag kan inte byta modell åt dig — det gör du i stegredigeraren.")
      ).toBeNull()
    );
  });

  it("marks the steps a replacement plan changed", async () => {
    let seed: ((state: object) => void) | undefined;
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: makeCreateState(),
      onservice: (service) => (seed = (state) => service.seedState(state))
    });

    expect(screen.queryByText(m.ai_builder_node_updated())).toBeNull();

    seed!({
      currentPlan: makePlan({
        plan_id: "plan-2",
        status: "proposed",
        proposal: makeProposal({
          spec: {
            flow_name: "Ljud till PDF",
            flow_description: "",
            form_fields: [],
            steps: [
              makeTranscribeStep(),
              makeRenderStep({
                assistant_spec: {
                  instructions: "Rendera PDF med en försättssida.",
                  knowledge_refs: [],
                  model_ref: null
                }
              })
            ]
          }
        })
      })
    });

    expect(await screen.findByText(m.ai_builder_plan_updated_detail({ count: 1 }))).toBeTruthy();
    expect(screen.getAllByText(m.ai_builder_node_updated()).length).toBeGreaterThan(0);
  });
});

describe("BuilderReviewScreen recovery surfaces", () => {
  it("renders one conflict card for a stream conflict and clears it when the reload succeeds", async () => {
    // The stale conflict is also persisted on the committed turn, so a
    // refresh alone would rehydrate it; recovery must end with the card gone
    // and the reloaded plan on screen.
    const reloadedSession = makeSession({
      status: "awaiting_approval",
      target_kind: "create",
      flow_id: null,
      latest_plan_id: "plan-2",
      latest_turn: {
        client_turn_id: "11111111-1111-4111-8111-111111111111",
        state: "committed",
        user_message_id: "11111111-1111-4111-8111-111111111112",
        error: {
          schema_version: 2,
          code: "stale_plan_revision",
          category: "conflict",
          message: "Planen ändrades",
          phase: "planner",
          eneo_error_code: 9000,
          request_id: "req-1",
          diagnostic_context: null,
          details: {}
        },
        requires_duplicate_provider_spend_acknowledgement: false,
        retry_request: {
          client_turn_id: "11111111-1111-4111-8111-111111111111",
          message: "Lägg till ett steg",
          model_id: null,
          ui_language: "sv",
          acknowledge_duplicate_provider_spend: false
        }
      }
    });
    const transport = {
      fetch: vi.fn(async (route: string) =>
        route.endsWith("/sessions/{session_id}") ? reloadedSession : makePlan({ plan_id: "plan-2" })
      ),
      stream: vi.fn()
    } as unknown as AIBuilderClientTransport;
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: { ...makeCreateState(), error: makeError("stale_plan_revision") },
      transport
    });

    expect(screen.getAllByText(m.ai_builder_conflict_elsewhere_title())).toHaveLength(1);
    expect(screen.getByText(m.ai_builder_conflict_stale_plan())).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_conflict_refresh() }));

    await waitFor(() => {
      expect(screen.queryByText(m.ai_builder_conflict_elsewhere_title())).toBeNull();
    });
    expect(screen.getByRole("button", { name: m.ai_builder_approve_create() })).toBeTruthy();
  });

  it("keeps the conflict card when the reload fails", async () => {
    const transport = {
      fetch: vi.fn(async () => {
        throw new Error("offline");
      }),
      stream: vi.fn()
    } as unknown as AIBuilderClientTransport;
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: { ...makeCreateState(), error: makeError("stale_plan_revision") },
      transport
    });

    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_conflict_refresh() }));
    await waitFor(() => expect(transport.fetch).toHaveBeenCalled());

    expect(screen.getAllByText(m.ai_builder_conflict_elsewhere_title())).toHaveLength(1);
  });

  it("offers only the cost-acknowledging retry for an unknown provider outcome", async () => {
    const acknowledge = vi.fn();
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeRecoverableSession("provider_outcome_unknown"),
        currentPlan: null,
        error: makeError("unknown")
      },
      screenProps: { showGenerationFailure: true },
      onservice: (service) => {
        service.acknowledgeAndRetryLatestTurn = acknowledge;
      }
    });

    expect(screen.getByText(m.ai_builder_generation_failed_title())).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.ai_builder_turn_retry() })).toBeNull();

    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_turn_retry_with_cost_acknowledgement() })
    );
    expect(acknowledge).toHaveBeenCalledOnce();
  });

  it("keeps the plain retry and the conversation escape for a pre-provider failure", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeRecoverableSession("failed_before_provider"),
        currentPlan: null,
        error: makeError("unknown")
      },
      screenProps: { showGenerationFailure: true }
    });

    expect(screen.getByRole("button", { name: m.ai_builder_turn_retry() })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: m.ai_builder_turn_retry_with_cost_acknowledgement() })
    ).toBeNull();
    expect(screen.getByRole("button", { name: m.ai_builder_show_conversation() })).toBeTruthy();
  });
});

// ---- fixtures --------------------------------------------------------------

function makeError(code: string): AIBuilderError {
  return {
    schema_version: 2,
    code,
    category: code === "unknown" ? "internal" : "conflict",
    message: "Något gick fel",
    phase: "client",
    request_id: null,
    eneo_error_code: null,
    diagnostic_context: null,
    details: {}
  };
}

function makeTranscribeStep(overrides: Partial<StepSpec> = {}): StepSpec {
  return {
    plan_step_ref: "step_a",
    existing_step_ref: null,
    name: "Transkribera ljud",
    assistant_spec: {
      instructions: "Transkribera det uppladdade ljudet.",
      knowledge_refs: [],
      model_ref: null
    },
    input_source: "flow_input",
    input_type: "audio",
    output_mode: "transcribe_only",
    output_type: "text",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    review_policy: { mode: "view" },
    ...overrides
  };
}

function makeRenderStep(overrides: Partial<StepSpec> = {}): StepSpec {
  return {
    plan_step_ref: "step_b",
    existing_step_ref: null,
    name: "Rendera PDF",
    assistant_spec: {
      instructions: "Rendera rapporten till PDF.",
      knowledge_refs: [],
      model_ref: null
    },
    input_source: "previous_step",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "pdf",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    ...overrides
  };
}

function makeCreateState() {
  return {
    session: makeSession({
      status: "awaiting_approval",
      target_kind: "create" as const,
      flow_id: null,
      latest_plan_id: "plan-1"
    }),
    currentPlan: makePlan({ status: "proposed" })
  };
}

function makeSession(overrides: Partial<AIBuilderSession> = {}): AIBuilderSession {
  return {
    session_id: "session-1",
    status: "chatting",
    target_kind: "edit",
    flow_id: "flow-1",
    latest_plan_id: null,
    conversation: [],
    ...overrides
  };
}

function makeRecoverableSession(
  state: "failed_before_provider" | "provider_outcome_unknown"
): AIBuilderSession {
  return makeSession({
    status: "chatting",
    target_kind: "create",
    flow_id: null,
    latest_turn: {
      client_turn_id: "11111111-1111-4111-8111-111111111111",
      state,
      user_message_id: "11111111-1111-4111-8111-111111111112",
      error: null,
      requires_duplicate_provider_spend_acknowledgement: state === "provider_outcome_unknown",
      retry_request: {
        client_turn_id: "11111111-1111-4111-8111-111111111111",
        message: "Bygg ett flöde",
        ui_language: "sv",
        acknowledge_duplicate_provider_spend: false
      }
    }
  });
}

function makePlan(overrides: Partial<ProposedPlan> = {}): ProposedPlan {
  return {
    plan_id: "plan-1",
    status: "proposed",
    proposal: makeProposal(),
    ...overrides
  };
}

function makeProposal(overrides: Partial<ProposedPlan["proposal"]> = {}): ProposedPlan["proposal"] {
  return {
    spec: {
      flow_name: "Ljud till PDF",
      flow_description: "Transkriberar ljud och skriver en PDF-rapport.",
      steps: [makeTranscribeStep(), makeRenderStep()],
      form_fields: []
    },
    assumptions: ["Rapporten skrivs på svenska."],
    lint_warnings: [],
    execution_shape: {
      completion_model_step_count: 1,
      transcription_model_step_count: 1,
      deterministic_step_count: 1,
      schema_constrained_step_count: 0,
      mapped_step_upper_bounds: [
        { plan_step_ref: "step_a", execution_mode: "per_source", maximum_items: 3 }
      ]
    },
    ...overrides
  };
}

export type { AIBuilderTelemetrySummary };

function makeSpace({
  transcriptionModels
}: {
  transcriptionModels: Array<{ can_access?: boolean }>;
}) {
  return {
    id: "space-1",
    name: "Space",
    personal: false,
    organization: false,
    permissions: [],
    members: { items: [], permissions: [] },
    group_members: { items: [], permissions: [] },
    applications: {
      assistants: { items: [], permissions: [] },
      group_chats: { items: [], permissions: [] },
      apps: { items: [], permissions: [] },
      services: { items: [], permissions: [] }
    },
    knowledge: {
      websites: { items: [], permissions: [] },
      groups: { items: [], permissions: [] },
      integration_knowledge_list: { items: [], permissions: [] }
    },
    completion_models: [{ can_access: true }],
    transcription_models: transcriptionModels,
    mcp_servers: []
  } as unknown as Pick<Space, "completion_models" | "transcription_models"> & Partial<Space>;
}
