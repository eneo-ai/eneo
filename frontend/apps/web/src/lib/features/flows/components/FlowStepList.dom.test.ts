import { cleanup, render, screen } from "@testing-library/svelte";
import { readable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";

import { flowStepFixture } from "$lib/features/flows/flowStepTestFixture";
import { m } from "$lib/paraglide/messages";

import FlowStepList from "./FlowStepList.svelte";

const SEARCH = {
  mcp_server_id: "server-1",
  mcp_server_name: "Ärenden",
  mcp_server_security_level: null,
  tool_id: "tool-search",
  tool_name: "search_cases",
  tool_description: null,
  input_schema: null,
  refusal: null
};

vi.mock("$lib/features/flows/FlowUserMode", () => ({
  getFlowUserMode: () => readable("power_user")
}));
vi.mock("$lib/features/flows/FlowEditor", () => ({
  getFlowEditor: () => ({
    state: {
      toolOptions: readable({
        status: "loaded",
        options: [SEARCH],
        classificationsEnabled: false,
        refreshing: false
      })
    },
    addStep: vi.fn()
  })
}));

afterEach(() => {
  cleanup();
});

describe("FlowStepList", () => {
  // Kills: the step list leaves the editor's tool list out, so a step that
  // reads a chosen tool still says only "a tool".
  it("names the tool a step reads", () => {
    render(FlowStepList, {
      steps: [
        flowStepFixture({
          input_source: "tool",
          input_config: {
            tool: { mcp_server_id: "server-1", tool_id: "tool-search", arguments: {} }
          }
        })
      ],
      activeStepId: null,
      isPublished: false
    });

    expect(
      screen.getByText(
        m.flow_step_reads({
          what: m.flow_step_reads_tool_named({ tool: "search_cases", server: "Ärenden" })
        })
      )
    ).toBeTruthy();
  });
});
