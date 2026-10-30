import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, expect, it, vi } from "vitest";

// The real manager, so two quick toggles go through its queue as they do on the page.
const { holder } = vi.hoisted(() => ({ holder: { manager: null as unknown } }));
vi.mock("$lib/features/spaces/SpacesManager", async (importOriginal) => {
  const actual = await importOriginal<typeof import("$lib/features/spaces/SpacesManager")>();
  return { ...actual, getSpacesManager: () => holder.manager };
});

import { SpacesManager } from "$lib/features/spaces/SpacesManager";
import { CAPABILITIES } from "$lib/features/mcp/capabilities";
import { m } from "$lib/paraglide/messages";
import CapabilityRow from "./CapabilityRow.svelte";
import SelectMCPServers from "./SelectMCPServers.svelte";

type Deferred = { promise: Promise<unknown>; resolve: (value: unknown) => void };
function deferred(): Deferred {
  let resolve!: (value: unknown) => void;
  const promise = new Promise<unknown>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

type Tool = { id: string; name: string; is_enabled: boolean };
type SpaceState = {
  enabled_capabilities?: string[];
  mcp_servers?: { id: string; name: string; tools: Tool[] }[];
};

function space(state: SpaceState) {
  return {
    id: "space-1",
    name: "Space",
    personal: false,
    organization: false,
    members: { items: [] },
    permissions: [],
    skill_permissions: [],
    applications: null,
    knowledge: {
      groups: { items: [], permissions: [] },
      websites: { items: [], permissions: [] },
      integration_knowledge_list: { items: [], permissions: [] }
    },
    completion_models: [],
    embedding_models: [],
    transcription_models: [],
    security_classification: null,
    available_capabilities: CAPABILITIES.map(({ purpose }) => ({ purpose, available: true })),
    enabled_capabilities: [],
    mcp_servers: [],
    ...state
  };
}

let responses: Deferred[];
const update = vi.fn();

function useManager(state: SpaceState) {
  holder.manager = SpacesManager({
    spaces: [],
    currentSpace: space(state) as never,
    eneo: { spaces: { update } } as never
  });
}

beforeEach(() => {
  responses = [deferred(), deferred()];
  update.mockReset();
  update.mockImplementation(() => responses[update.mock.calls.length - 1]!.promise);
});

const sent = (call: number) => (update.mock.calls[call]![0] as { update: unknown }).update;

it("keeps both capabilities when two rows are switched on in quick succession", async () => {
  const [webSearch, imageGeneration] = CAPABILITIES;
  useManager({});
  render(CapabilityRow, { capability: webSearch! });
  render(CapabilityRow, { capability: imageGeneration! });

  await page.getByRole("switch", { name: m.web_search() }).click();
  await page.getByRole("switch", { name: m.image_generation() }).click();
  await expect.poll(() => update.mock.calls.length).toBe(1);

  responses[0]!.resolve(space({ enabled_capabilities: ["web_search"] }));
  await expect.poll(() => update.mock.calls.length).toBe(2);
  expect(sent(1)).toEqual({ enabled_capabilities: ["web_search", "image_generation"] });

  responses[1]!.resolve(space({ enabled_capabilities: ["web_search", "image_generation"] }));
  await expect.element(page.getByRole("switch", { name: m.web_search() })).toBeChecked();
  await expect.element(page.getByRole("switch", { name: m.image_generation() })).toBeChecked();
});

it("keeps both servers when two are switched on in quick succession", async () => {
  useManager({});
  const server = (id: string) => ({ id, name: `Server ${id}`, tools: [] });
  render(SelectMCPServers, { selectableServers: [server("s1"), server("s2")] });

  await page.getByRole("switch", { name: "Server s1" }).click();
  await page.getByRole("switch", { name: "Server s2" }).click();
  await expect.poll(() => update.mock.calls.length).toBe(1);

  responses[0]!.resolve(space({ mcp_servers: [{ id: "s1", name: "Server s1", tools: [] }] }));
  await expect.poll(() => update.mock.calls.length).toBe(2);
  expect(sent(1)).toEqual({ mcp_servers: [{ id: "s1" }, { id: "s2" }], mcp_tools: [] });

  responses[1]!.resolve(
    space({
      mcp_servers: [
        { id: "s1", name: "Server s1", tools: [] },
        { id: "s2", name: "Server s2", tools: [] }
      ]
    })
  );
  await expect.element(page.getByRole("switch", { name: "Server s2" })).toBeChecked();
  await expect.element(page.getByRole("switch", { name: "Server s1" })).toBeChecked();
});

it("keeps both tools when two are switched in quick succession", async () => {
  const tools = (t1: boolean, t2: boolean) => [
    { id: "t1", name: "Tool one", is_enabled: t1 },
    { id: "t2", name: "Tool two", is_enabled: t2 }
  ];
  const withTools = (t1: boolean, t2: boolean) => ({
    mcp_servers: [{ id: "s1", name: "Server s1", tools: tools(t1, t2) }]
  });
  useManager(withTools(false, false));
  render(SelectMCPServers, {
    selectableServers: [{ id: "s1", name: "Server s1", tools: [] }]
  });

  await page.getByRole("button", { name: m.governance_mcp_show_tools() }).click();
  await page.getByRole("switch", { name: "Tool one" }).click();
  await page.getByRole("switch", { name: "Tool two" }).click();
  await expect.poll(() => update.mock.calls.length).toBe(1);

  responses[0]!.resolve(space(withTools(true, false)));
  await expect.poll(() => update.mock.calls.length).toBe(2);
  expect(sent(1)).toEqual({
    mcp_tools: [
      { tool_id: "t1", is_enabled: true },
      { tool_id: "t2", is_enabled: true }
    ]
  });

  responses[1]!.resolve(space(withTools(true, true)));
  await expect.element(page.getByRole("switch", { name: "Tool one" })).toBeChecked();
  await expect.element(page.getByRole("switch", { name: "Tool two" })).toBeChecked();
});
