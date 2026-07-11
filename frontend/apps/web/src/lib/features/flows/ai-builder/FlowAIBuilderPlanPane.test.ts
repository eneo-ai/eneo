// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/svelte";
import type { Space } from "@eneo/eneo-js";
import { afterEach, describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import type { AIBuilderSession, AIBuilderStatus, ProposedPlan, StepSpec } from "./protocol";
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
        lint_warnings: [],
        risk_acknowledgments: []
      }
    })
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
      lint_warnings: [],
      risk_acknowledgments: []
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
      mcp_server_refs: [],
      mcp_tool_refs: [],
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
