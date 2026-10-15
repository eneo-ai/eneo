import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, expect, it, vi } from "vitest";
import * as api from "$lib/test/mcpTestApi";

// The page a flow link opens needs the flows_manage permission.
const access = vi.hoisted(() => ({ flowsManage: true }));
vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    user: { hasPermission: (name: string) => name === "flows_manage" && access.flowsManage }
  })
}));
import { m } from "$lib/paraglide/messages";
import MCPServerFlowUsage from "./MCPServerFlowUsage.svelte";

afterEach(() => {
  cleanup();
  access.flowsManage = true;
  vi.unstubAllGlobals();
});

const used = (flow_id: string, space_id: string, tool_ids: string[]) => ({
  flow_id,
  flow_name: `Flow ${flow_id}`,
  space_id,
  space_name: `Space ${space_id}`,
  published_version: 2,
  tool_ids
});
// The usage answer, and the admin's own spaces: only "mine".
const answer = (usage: object) => (url: string) =>
  Promise.resolve(
    Response.json(url.includes("/flow-usage") ? usage : { items: [{ id: "mine", name: "Mine" }] })
  );
const show = (fetchAnswer: (url: string) => Promise<Response>) => {
  api.stubFetch((url) => fetchAnswer(String(url)));
  render(MCPServerFlowUsage, {
    mcpServerId: "s1",
    eneoClient: api.testEneo(),
    toolLabel: (id: string) => `label ${id}`
  });
};

it("counts every using flow, links only the flows of the admin's spaces and says the list is cut", async () => {
  // Kills: the count shown is the listed part, a flow outside the admin's spaces gets a link
  // (or one inside gets none), a flow's tools are not named, the cut list is not announced
  show(
    answer({ total_count: 3, items: [used("a", "mine", ["t1", "t2"]), used("b", "other", ["t2"])] })
  );
  await fireEvent.click(await screen.findByText(m.mcp_flow_usage_plural({ count: 3 })));

  expect(screen.getByRole("link", { name: "Flow a" }).getAttribute("href")).toContain(
    "/spaces/mine/flows/a"
  );
  expect(screen.queryByRole("link", { name: "Flow b" })).toBeNull();
  expect(screen.getByText("Flow b")).toBeTruthy();
  expect(screen.getByText(m.mcp_flow_usage_tools({ tools: "label t1, label t2" }))).toBeTruthy();
  expect(screen.getByText(m.mcp_flow_usage_shown({ shown: 2, total: 3 }))).toBeTruthy();
});

it.each([
  ["no using flow", answer({ total_count: 0, items: [] }), m.mcp_flow_usage_none()],
  ["a refused read", api.refused, `${m.mcp_flow_usage_failed()}: Refused`]
])("says so for %s", async (_case, fetchAnswer, text) => {
  // Kills: an empty usage shows a count of 0 flows, a failed read stays loading or is hidden
  show(fetchAnswer);
  expect(await screen.findByText(text)).toBeTruthy();
});

it("lists the flows without links when the admin's spaces cannot be read", async () => {
  // Kills: a failed read of the admin's spaces hides the whole usage answer
  const usage = { total_count: 1, items: [used("a", "mine", ["t1"])] };
  show((url) => (url.includes("/flow-usage") ? answer(usage)(url) : api.refused()));
  await fireEvent.click(await screen.findByText(m.mcp_flow_usage_singular()));
  expect(screen.getByText("Flow a")).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Flow a" })).toBeNull();
});

it("lists the flows without links when the admin may not open flows", async () => {
  // Kills: a flow in one of the admin's spaces is linked without the flows_manage permission
  access.flowsManage = false;
  show(answer({ total_count: 1, items: [used("a", "mine", ["t1"])] }));
  await fireEvent.click(await screen.findByText(m.mcp_flow_usage_singular()));
  expect(screen.getByText("Flow a")).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Flow a" })).toBeNull();
});
