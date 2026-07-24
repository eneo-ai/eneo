// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import type { Space } from "@eneo/eneo-js";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import type {
  AIBuilderSession,
  AIBuilderStatus,
  AIBuilderTelemetrySummary,
  ProposedPlan,
  StepSpec
} from "./protocol";
import FlowAIBuilderPlanPaneHarness from "./test-harnesses/FlowAIBuilderPlanPaneHarness.svelte";

afterEach(() => {
  cleanup();
});

describe("FlowAIBuilderPlanPane", () => {
  it.each([
    ["architecture_committed", m.ai_builder_generating()],
    ["architecture_revised", m.ai_builder_updating_plan()],
    ["repairing", m.ai_builder_status_repairing()]
  ] satisfies ReadonlyArray<readonly [AIBuilderStatus, string]>)(
    "renders the generated %s status",
    (statusMessage, expectedLabel) => {
      render(FlowAIBuilderPlanPaneHarness, {
        currentSpace: makeSpace({ transcriptionModels: [] }),
        state: {
          isStreaming: true,
          statusMessage
        }
      });

      expect(screen.getByText(expectedLabel)).toBeTruthy();
    }
  );

  it("blocks creating from an audio plan until an accessible transcription model exists", () => {
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: false }] }),
      state: makeApprovedCreatePlanState({
        step: { input_source: "flow_input", input_type: "audio" }
      })
    });

    expect(screen.getByText(m.ai_builder_missing_transcription_model_title())).toBeTruthy();
    expect(
      screen.getByRole("button", { name: m.ai_builder_approve_create() }).hasAttribute("disabled")
    ).toBe(true);
  });

  it("allows creating from an audio plan when an accessible transcription model exists", () => {
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({
        transcriptionModels: [{ can_access: false }, { can_access: true }]
      }),
      state: makeApprovedCreatePlanState({
        step: { input_source: "flow_input", input_type: "audio" }
      })
    });

    expect(screen.queryByText(m.ai_builder_missing_transcription_model_title())).toBeNull();
    expect(
      screen.getByRole("button", { name: m.ai_builder_approve_create() }).hasAttribute("disabled")
    ).toBe(false);
  });

  it("renders exactly one creation action in create mode and never a separate apply", () => {
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({
          status: "awaiting_approval",
          target_kind: "create",
          flow_id: null
        }),
        currentPlan: makePlan({ status: "proposed" })
      }
    });

    expect(screen.getAllByRole("button", { name: m.ai_builder_approve_create() })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: m.ai_builder_apply() })).toBeNull();
    expect(screen.queryByRole("button", { name: m.ai_builder_approve() })).toBeNull();
    expect(screen.getByText(m.ai_builder_nothing_created_yet())).toBeTruthy();
  });

  it("keeps the explicit approve-then-apply contract in edit mode", () => {
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({ status: "awaiting_approval" }),
        currentPlan: makePlan({ status: "proposed" })
      }
    });
    expect(screen.getByRole("button", { name: m.ai_builder_approve() })).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.ai_builder_approve_create() })).toBeNull();
    cleanup();

    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({ status: "awaiting_approval" }),
        currentPlan: makePlan({ status: "approved" })
      }
    });
    expect(screen.getByRole("button", { name: m.ai_builder_apply() })).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.ai_builder_approve_create() })).toBeNull();
  });

  it("keeps one recovery action after a confirmed creation failure", () => {
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({
          status: "awaiting_approval",
          target_kind: "create",
          flow_id: null
        }),
        currentPlan: makePlan({ status: "proposed" }),
        applyError: makeApplyError(),
        createFailureOutcome: "confirmed_not_applied"
      }
    });

    // The banner explains; the footer owns the single retry action.
    expect(screen.getByText(m.ai_builder_create_failed_title())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_plan_unchanged())).toBeTruthy();
    expect(screen.getAllByRole("button", { name: m.ai_builder_turn_retry() })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: m.ai_builder_approve_create() })).toBeNull();
    expect(
      screen.getByRole("button", { name: m.ai_builder_modify() }).hasAttribute("disabled")
    ).toBe(false);
  });

  it("makes no persistence claims and blocks mutation on an unknown creation outcome", () => {
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({
          status: "awaiting_approval",
          target_kind: "create",
          flow_id: null
        }),
        currentPlan: makePlan({ status: "proposed" }),
        applyError: makeApplyError(),
        createFailureOutcome: "unknown"
      }
    });

    expect(screen.getByText(m.ai_builder_create_unknown_title())).toBeTruthy();
    expect(screen.queryByText(m.ai_builder_create_failed_body())).toBeNull();
    expect(screen.queryByText(m.ai_builder_plan_unchanged())).toBeNull();
    expect(screen.getAllByRole("button", { name: m.ai_builder_turn_retry() })).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: m.ai_builder_modify() }).hasAttribute("disabled")
    ).toBe(true);
  });

  it("keeps the retry action when reconciliation shows the plan applied", () => {
    // After a lost response the driver may refresh to an applied plan while
    // the replay call fails: canApprove/canApply are both false, but the
    // footer must still own a retry, and the trust copy must not claim that
    // nothing was created.
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({
          status: "applied",
          target_kind: "create",
          flow_id: "flow-1"
        }),
        currentPlan: makePlan({ status: "applied" }),
        applyError: makeApplyError(),
        createFailureOutcome: "unknown"
      }
    });

    expect(screen.getByText(m.ai_builder_create_unknown_title())).toBeTruthy();
    expect(screen.getAllByRole("button", { name: m.ai_builder_turn_retry() })).toHaveLength(1);
    expect(screen.queryByText(m.ai_builder_nothing_created_yet())).toBeNull();
  });

  it("renders the §5 plan header meta and 'Så fungerar flödet' as the steps section", () => {
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: makeApprovedCreatePlanState({ step: {} })
    });

    expect(screen.getByText(m.ai_builder_draft_pill())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_plan_meta_nothing_created())).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: m.ai_builder_how_flow_works(), level: 3 })
    ).toBeTruthy();
    // The action bar no longer offers "Föreslå planändring" — the refinement
    // composer is that path (§5 glossary).
    expect(screen.queryByRole("button", { name: m.ai_builder_plan_suggest_change() })).toBeNull();
  });

  it("keeps token usage visible in the proposal metadata in Enkel and Avancerad", () => {
    const state = {
      session: makeSession({ telemetry: makeTelemetry() }),
      currentPlan: makePlan()
    };

    const enkel = render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state
    });
    expect(screen.getByText(m.ai_builder_plan_meta_nothing_created())).toBeTruthy();
    expect(screen.getByRole("button", { name: m.ai_builder_token_usage_title() })).toBeTruthy();
    enkel.unmount();

    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state,
      userMode: "power_user"
    });
    expect(screen.getByRole("button", { name: m.ai_builder_token_usage_title() })).toBeTruthy();
  });

  it("hides technical assumptions in Enkel and shows them collapsed in Avancerad", async () => {
    const state = {
      session: makeSession({ status: "awaiting_approval", target_kind: "create", flow_id: null }),
      currentPlan: makePlan({
        proposal: {
          spec: { flow_name: "Flow", flow_description: "", steps: [], form_fields: [] },
          assumptions: ["Underlaget är på svenska.", "En körning i taget."],
          lint_warnings: []
        }
      })
    };

    const enkel = render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state,
      userMode: "user"
    });
    expect(screen.queryByText(/Tekniska antaganden|Technical assumptions/)).toBeNull();
    enkel.unmount();

    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state,
      userMode: "power_user"
    });
    const trigger = screen.getByRole("button", {
      name: new RegExp(
        `${m.ai_builder_technical_assumptions().replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} \\(2\\)`
      )
    });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    await fireEvent.click(trigger);
    expect(screen.getByText("Underlaget är på svenska.")).toBeTruthy();
  });

  it("keeps an expanded step expanded across Diagram↔Detaljer switches", async () => {
    // §2: both views keep state — bits-ui keeps inactive tab content mounted
    // with the hidden attribute; this pins that contract against regressions.
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: makeApprovedCreatePlanState({ step: {} })
    });

    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_details() }));
    const stepTrigger = () => screen.getByRole("button", { name: /Transcribe audio/ });
    await fireEvent.click(stepTrigger());
    expect(stepTrigger().getAttribute("aria-expanded")).toBe("true");

    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_diagram() }));
    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_details() }));
    expect(stepTrigger().getAttribute("aria-expanded")).toBe("true");
  });

  it("renders the §5 wait-state copy with only backend-real phase lines", () => {
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({ status: "chatting", target_kind: "create", flow_id: null }),
        isStreaming: true,
        statusMessage: "architecture_committed"
      }
    });

    // The status line maps 1:1 to a REAL backend phase (§7.2 — no simulated
    // progress), and the §5 expectation copy frames the wait.
    expect(screen.getByText(m.ai_builder_generating())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_wait_expectation())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_wait_footer_note())).toBeTruthy();
  });

  it("E1 with an unknown provider outcome offers ONLY the cost-acknowledging retry", async () => {
    const acknowledge = vi.fn();
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeRecoverableSession("provider_outcome_unknown"),
        currentPlan: null,
        error: makeApplyError()
      },
      paneProps: { showGenerationFailure: true },
      onservice: (service) => {
        service.acknowledgeAndRetryLatestTurn = acknowledge;
      }
    });

    const costButton = screen.getByRole("button", {
      name: m.ai_builder_turn_retry_with_cost_acknowledgement()
    });
    expect(screen.queryByRole("button", { name: m.ai_builder_turn_retry() })).toBeNull();

    await fireEvent.click(costButton);
    expect(acknowledge).toHaveBeenCalledOnce();
  });

  it("does not announce a resumed session's first plan as an update", async () => {
    let service: { seedState: (state: object) => void } | undefined;
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({
          session_id: "session-a",
          status: "awaiting_approval",
          target_kind: "create",
          flow_id: null
        }),
        currentPlan: { ...makePlan(), updated_at: "2026-07-12T10:00:00Z" }
      },
      onservice: (instance) => (service = instance)
    });

    // Switching to session B with a DIFFERENT plan must not read as an update.
    service!.seedState({
      session: makeSession({
        session_id: "session-b",
        status: "awaiting_approval",
        target_kind: "create",
        flow_id: null
      }),
      currentPlan: { ...makePlan({ plan_id: "plan-b" }), updated_at: "2026-07-12T11:00:00Z" }
    });
    await waitFor(() => expect(screen.queryByText(m.ai_builder_plan_updated_receipt())).toBeNull());
  });

  it("renders the E1 generation-failure banner with the recovery contract intact", () => {
    const recoverable = makeRecoverableSession();
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: recoverable,
        currentPlan: null,
        error: makeApplyError()
      },
      paneProps: { showGenerationFailure: true }
    });

    expect(screen.getByText(m.ai_builder_generation_failed_title())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_generation_failed_body())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_generation_failed_late_note())).toBeTruthy();
    // failed_before_provider → plain retry, never the cost-acknowledging one.
    expect(screen.getByRole("button", { name: m.ai_builder_turn_retry() })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: m.ai_builder_turn_retry_with_cost_acknowledgement() })
    ).toBeNull();
    expect(screen.getByRole("button", { name: m.ai_builder_show_conversation() })).toBeTruthy();
  });

  it("announces a plan update once and shows the header receipt", async () => {
    let service: { seedState: (state: object) => void } | undefined;
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({ status: "awaiting_approval", target_kind: "create", flow_id: null }),
        currentPlan: { ...makePlan(), updated_at: "2026-07-12T10:00:00Z" }
      },
      onservice: (instance) => (service = instance)
    });

    expect(screen.queryByText(m.ai_builder_plan_updated_receipt())).toBeNull();

    service!.seedState({
      currentPlan: { ...makePlan(), updated_at: "2026-07-12T10:05:00Z" }
    });
    expect(await screen.findByText(m.ai_builder_plan_updated_receipt())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_plan_updated_announce())).toBeTruthy();
  });

  it("renders the details view as an ordered list of steps", async () => {
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: makeApprovedCreatePlanState({ step: {} })
    });

    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_details() }));
    const lists = screen.getAllByRole("list");
    const stepList = lists.find((list) => list.tagName === "OL" && list.querySelector("li"));
    expect(stepList).toBeTruthy();
  });
});

function makeApplyError() {
  return {
    schema_version: 2 as const,
    code: "unknown" as const,
    category: "internal" as const,
    message: "Creation failed",
    phase: "client" as const,
    request_id: null,
    eneo_error_code: null,
    diagnostic_context: null,
    details: {}
  };
}

function makeApprovedCreatePlanState({ step }: { step: Partial<StepSpec> }) {
  return {
    session: makeSession({
      status: "awaiting_approval",
      target_kind: "create",
      flow_id: null
    }),
    currentPlan: makePlan({
      status: "approved",
      proposal: {
        spec: {
          flow_name: "Audio intake",
          flow_description: "Transcribe uploaded audio.",
          steps: [makeStep(step)],
          form_fields: []
        },
        assumptions: [],
        lint_warnings: []
      }
    })
  };
}

function makeRecoverableSession(
  state: "failed_before_provider" | "provider_outcome_unknown" = "failed_before_provider"
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

function makeTelemetry(): AIBuilderTelemetrySummary {
  return {
    planner_request_count: 1,
    clarification_question_count: 0,
    prompt_tokens_total: 1200,
    completion_tokens_total: 240,
    total_tokens_total: 1440,
    tool_call_count_total: 0,
    auxiliary_llm_call_count: 0,
    architecture_commit_count: 1,
    repair_attempts_total: 0,
    parse_repair_attempts_total: 0,
    wall_clock_ms_total: 800,
    llm_calls_made_total: 2,
    token_usage_estimated: false,
    last_request_id: "request-1",
    last_model: "openai/gpt-5.4-nano",
    last_finish_reason: "stop",
    last_outcome_kind: "dispatched",
    last_token_usage_source: "provider",
    last_token_usage_estimated: false
  };
}

function makePlan(overrides: Partial<ProposedPlan> = {}): ProposedPlan {
  return {
    plan_id: "plan-1",
    status: "proposed",
    proposal: {
      spec: {
        flow_name: "Flow",
        flow_description: "",
        steps: [],
        form_fields: []
      },
      assumptions: [],
      lint_warnings: []
    },
    ...overrides
  };
}

function makeStep(overrides: Partial<StepSpec>): StepSpec {
  return {
    plan_step_ref: "step_a",
    existing_step_ref: null,
    name: "Transcribe audio",
    assistant_spec: {
      instructions: "Transcribe the uploaded audio.",
      knowledge_refs: [],
      model_ref: null
    },
    input_source: "flow_input",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    ...overrides
  };
}

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
