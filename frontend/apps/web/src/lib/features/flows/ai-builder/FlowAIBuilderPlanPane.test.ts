// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/svelte";
import type { Space } from "@eneo/eneo-js";
import { afterEach, describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import type { AIBuilderSession, ProposedPlan, StepSpec } from "./protocol";
import FlowAIBuilderPlanPaneHarness from "./test-harnesses/FlowAIBuilderPlanPaneHarness.svelte";

afterEach(() => {
  cleanup();
});

describe("FlowAIBuilderPlanPane", () => {
  it("blocks applying a create audio plan until an accessible transcription model exists", () => {
    render(FlowAIBuilderPlanPaneHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: false }] }),
      state: makeApprovedCreatePlanState({
        step: { input_source: "flow_input", input_type: "audio" }
      })
    });

    expect(screen.getByText(m.ai_builder_missing_transcription_model_title())).toBeTruthy();
    expect(
      screen.getByRole("button", { name: m.ai_builder_apply() }).hasAttribute("disabled")
    ).toBe(true);
  });

  it("allows applying a create audio plan when an accessible transcription model exists", () => {
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
      screen.getByRole("button", { name: m.ai_builder_apply() }).hasAttribute("disabled")
    ).toBe(false);
  });
});

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
