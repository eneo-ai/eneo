import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import type { FlowGraphToolNode } from "$lib/features/flows/flowGraphToolNode";
import FlowNodeTool from "./FlowNodeTool.svelte";

vi.mock("@xyflow/svelte", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@xyflow/svelte")>()),
  Handle: (await import("./FlowHandleStub.fixture.svelte")).default
}));

afterEach(cleanup);

const named: FlowGraphToolNode = {
  listState: "loaded",
  toolName: "query_detail_view",
  serverName: "SEAB SQL",
  problem: null,
  rows: [{ name: "days", kind: "step", stepOrder: 1, field: "anomaly_days" }],
  hiddenCount: 0
};

// Kills a tool node that shows a generic source label instead of the tool and
// its server, or loses which step and field an argument reads.
it("names the tool, its server and what a bound argument reads", () => {
  render(FlowNodeTool, { props: { data: { tool: named, mode: "power_user" } } });
  expect(screen.getByText("query_detail_view")).toBeTruthy();
  expect(screen.getByText("SEAB SQL")).toBeTruthy();
  expect(screen.getByText(m.flow_graph_tool_badge())).toBeTruthy();
  expect(
    screen.getByText(
      m.flow_graph_tool_argument_from_step_field({ order: "1", field: "anomaly_days" })
    )
  ).toBeTruthy();
});

// Kills a node that invents a name it does not have, or hides that the
// space's list no longer offers the tool.
it("falls back to a generic name and says why a listed tool is gone", () => {
  render(FlowNodeTool, {
    props: {
      data: {
        tool: { ...named, toolName: null, serverName: null, problem: { kind: "not_listed" } },
        mode: "power_user"
      }
    }
  });
  expect(screen.getByText(m.flow_graph_tool_fallback())).toBeTruthy();
  expect(screen.getByText(m.flow_tool_stored_missing())).toBeTruthy();
  expect(screen.queryByText("query_detail_view")).toBeNull();
});
