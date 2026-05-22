// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import FlowAIBuilderStepCard from "./FlowAIBuilderStepCard.svelte";
import { AIBuilderIssueKind, buildAIBuilderDiagnosticReport } from "./aiBuilderDiagnosticReport";
import type { StepSpec } from "./protocol";

afterEach(() => {
  cleanup();
});

describe("FlowAIBuilderStepCard", () => {
  it("surfaces step-scoped MCP tools before approval", async () => {
    render(FlowAIBuilderStepCard, {
      step: makeStep({
        assistant_spec: {
          instructions: "Fetch the current time through MCP.",
          model_ref: "model-1",
          knowledge_refs: [],
          mcp_server_refs: ["server-time"],
          mcp_tool_refs: ["tool-current-time"]
        }
      }),
      stepNumber: 1,
      changeKind: "added",
      resolveMcpToolName: (ref) =>
        ref === "tool-current-time" ? "Time MCP: get_current_time" : null
    });

    expect(screen.getByText("MCP")).toBeTruthy();

    await fireEvent.click(
      screen.getByRole("button", { name: /^(Step|Steg) 1: Fetch time \((NEW|NY)\)$/ })
    );

    expect(await screen.findByText(/MCP( tools|-verktyg)/)).toBeTruthy();
    expect(screen.getByText("Time MCP: get_current_time")).toBeTruthy();
    expect(
      screen.getByText(/(Only this step gets these external tools|Endast detta steg får)/)
    ).toBeTruthy();
  });

  it("hides completion model details for transcribe-only steps by output mode", async () => {
    render(FlowAIBuilderStepCard, {
      step: makeStep({
        name: "Transcribe meeting audio",
        output_mode: "transcribe_only",
        assistant_spec: {
          instructions: "Transcribe the audio.",
          model_ref: "model.gpt-5-4-nano",
          knowledge_refs: [],
          mcp_server_refs: [],
          mcp_tool_refs: []
        }
      }),
      stepNumber: 1,
      resolveModelName: (ref) => (ref === "model.gpt-5-4-nano" ? "gpt-5.4 nano" : ref)
    });

    expect(screen.queryByText("gpt-5.4 nano")).toBeNull();

    await fireEvent.click(
      screen.getByRole("button", { name: /^(Step|Steg) 1: Transcribe meeting audio \((NEW|NY)\)$/ })
    );

    expect(screen.queryByText(/^(Model|Modell)$/)).toBeNull();
    expect(
      screen.getByText(/(Uses the flow transcription model|Använder flödets transkriberingsmodell)/)
    ).toBeTruthy();
  });

  it("shows completion model details for pass-through steps", async () => {
    render(FlowAIBuilderStepCard, {
      step: makeStep({
        assistant_spec: {
          instructions: "Summarize the transcript.",
          model_ref: "model.gpt-5-4-nano",
          knowledge_refs: [],
          mcp_server_refs: [],
          mcp_tool_refs: []
        }
      }),
      stepNumber: 1,
      resolveModelName: (ref) => (ref === "model.gpt-5-4-nano" ? "gpt-5.4 nano" : ref)
    });

    expect(screen.getAllByText("gpt-5.4 nano").length).toBeGreaterThan(0);
  });

  it("emits structured step edit context instead of relying on button text", async () => {
    const onsuggestchange = vi.fn();
    render(FlowAIBuilderStepCard, {
      step: makeStep({ plan_step_ref: "step_f", name: "Create final result" }),
      stepNumber: 6,
      planId: "plan-1",
      planStatus: "proposed",
      onsuggestchange
    });

    await fireEvent.click(
      screen.getByRole("button", {
        name: /^(Step|Steg) 6: Create final result \((NEW|NY)\)$/
      })
    );
    await fireEvent.click(
      screen.getByRole("button", { name: /^(Change this step|Ändra detta steg)$/ })
    );

    const intent = onsuggestchange.mock.calls[0]?.[0];
    expect(intent?.placeholder).toMatch(
      /(Describe the change|Beskriv ändringen).*6: Create final result/
    );
    expect(intent?.editContext).toEqual({
      scope: "step",
      plan_id: "plan-1",
      target_plan_step_ref: "step_f",
      target_existing_step_ref: null,
      target_step_name: "Create final result",
      target_step_number: 6
    });
  });

  it("copies a step diagnostic report with the call-site plan_step_ref", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText }
    });
    const step = makeStep({
      plan_step_ref: "step_f",
      name: "Create final result",
      input_type: "text",
      output_type: "json"
    });
    const buildDiagnosticReport = vi.fn(() =>
      buildAIBuilderDiagnosticReport({
        kind: "quality",
        surface: "step_quality",
        issue_kind: AIBuilderIssueKind.Other,
        session: {
          session_id: "session-1",
          target_kind: "edit",
          flow_id: "flow-1",
          latest_plan_id: "plan-1",
          telemetry: {
            last_request_id: "request-1",
            last_model: "gpt-5.4",
            last_outcome_kind: "planned"
          }
        },
        plan: { plan_id: "plan-1", status: "proposed" },
        step: {
          plan_step_ref: step.plan_step_ref,
          step_name: step.name,
          step_number: 6,
          input_type: step.input_type,
          output_type: step.output_type
        }
      })
    );

    render(FlowAIBuilderStepCard, {
      step,
      stepNumber: 6,
      planId: "plan-1",
      planStatus: "proposed",
      buildDiagnosticReport
    });
    expect(buildDiagnosticReport).not.toHaveBeenCalled();

    await fireEvent.click(
      screen.getByRole("button", {
        name: /^(Step|Steg) 6: Create final result \((NEW|NY)\)$/
      })
    );
    expect(buildDiagnosticReport).not.toHaveBeenCalled();
    await fireEvent.click(
      screen.getByRole("button", {
        name: /^(Copy technical details|Kopiera tekniska detaljer)$/
      })
    );

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(buildDiagnosticReport).toHaveBeenCalledTimes(1);
    const copied = writeText.mock.calls[0]?.[0];
    expect(copied).toContain("- plan_step_ref: step_f");
    expect(copied).toContain("- request_id_source: session_telemetry_last");
    expect(copied).not.toContain("Fetch the current time");
  });
});

function makeStep(overrides: Partial<StepSpec> = {}): StepSpec {
  return {
    plan_step_ref: "step_a",
    existing_step_ref: null,
    name: "Fetch time",
    assistant_spec: {
      instructions: "Fetch the current time.",
      model_ref: null,
      knowledge_refs: [],
      mcp_server_refs: [],
      mcp_tool_refs: []
    },
    input_source: "flow_input",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "json",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    ...overrides
  };
}
