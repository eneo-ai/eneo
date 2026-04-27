// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import FlowAIBuilderStepCard from "./FlowAIBuilderStepCard.svelte";
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

    await fireEvent.click(screen.getByRole("button", { name: "Step 1: Fetch time (NEW)" }));

    expect(await screen.findByText("MCP tools")).toBeTruthy();
    expect(screen.getByText("Time MCP: get_current_time")).toBeTruthy();
    expect(
      screen.getByText("Only this step gets these external tools when the flow runs.")
    ).toBeTruthy();
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
