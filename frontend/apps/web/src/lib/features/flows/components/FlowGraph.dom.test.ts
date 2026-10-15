import { cleanup, fireEvent, render, waitFor } from "@testing-library/svelte";
import { readable, writable } from "svelte/store";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import type { Flow, FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import type { ToolOptionsLoad } from "./tool/toolInputConfig";
import FlowGraph from "./FlowGraph.svelte";

const toolOptions = writable<ToolOptionsLoad>({ status: "loading" });

vi.mock("$lib/features/flows/FlowEditor", () => ({
  getFlowEditor: () => ({
    assistantRevision: readable(0),
    state: { toolOptions },
    loadAssistant: async () => null,
    insertStepAfter: async () => {}
  })
}));
vi.mock("$lib/features/flows/FlowUserMode", () => ({
  getFlowUserMode: () => writable("power_user")
}));

beforeAll(() => {
  // jsdom has neither; xyflow reads both while it mounts.
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {}
  })) as unknown as typeof window.matchMedia;
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
afterEach(cleanup);

const toolStep = (order: number, args: Record<string, unknown>): FlowStep => ({
  id: `s${order}`,
  assistant_id: `a${order}`,
  step_order: order,
  user_description: `Steg ${order}`,
  input_source: "tool",
  input_type: "json",
  output_mode: "pass_through",
  output_type: "json",
  input_config: { tool: { mcp_server_id: "srv", tool_id: `t${order}`, arguments: args } }
});
const seab = {
  id: "f",
  name: "SEAB",
  published_version: null,
  metadata_json: null,
  steps: [toolStep(1, {}), toolStep(2, { days: "{{step_1.output.structured.days}}" })]
} as unknown as Flow;

toolOptions.set({
  status: "loaded",
  classificationsEnabled: false,
  refreshing: false,
  options: [1, 2].map((order) => ({
    mcp_server_id: "srv",
    mcp_server_name: "SEAB SQL",
    mcp_server_security_level: null,
    tool_id: `t${order}`,
    tool_name: `tool_${order}`,
    tool_description: null,
    input_schema: null,
    refusal: null
  }))
});

// Kills a graph that leaves the tool node type unregistered (xyflow falls back
// to its default node), tabs to tool nodes after every step, drops the binding key from the legend, or does not
// carry the tool node's preview through to its step and its bound row.
it("draws tool nodes, keys the binding edge and lights a tool's step and row on hover", async () => {
  const { container, getByText } = render(FlowGraph, {
    props: { flow: seab, activeStepId: null }
  });
  await waitFor(() =>
    expect(container.querySelectorAll(".svelte-flow__node-tool_source")).toHaveLength(2)
  );
  expect(container.querySelector(".svelte-flow__node-default")).toBeNull();
  // Tab order is DOM order: each tool node right before the step it feeds.
  expect(
    [...container.querySelectorAll<HTMLElement>(".svelte-flow__node")].map((n) => n.dataset.id)
  ).toEqual(["tool-s1", "s1", "tool-s2", "s2", "output"]);
  expect(getByText("tool_2")).toBeTruthy();
  expect(getByText(m.flow_graph_legend_binding())).toBeTruthy();

  const tool2 = container.querySelector('.svelte-flow__node[data-id="tool-s2"]')!;
  await fireEvent.pointerEnter(tool2);
  await waitFor(() => {
    const step1 = container.querySelector('.svelte-flow__node[data-id="s1"] .flow-node')!;
    const step2 = container.querySelector('.svelte-flow__node[data-id="s2"] .flow-node')!;
    const tool1 = container.querySelector('.svelte-flow__node[data-id="tool-s1"] .flow-node')!;
    expect(step2.classList.contains("is-lifted")).toBe(true);
    expect(step1.classList.contains("is-lifted")).toBe(true);
    expect(tool1.classList.contains("is-dimmed")).toBe(true);
    expect(tool2.querySelector('[title^="days:"]')?.classList.contains("bg-accent-dimmer")).toBe(
      true
    );
  });
});
