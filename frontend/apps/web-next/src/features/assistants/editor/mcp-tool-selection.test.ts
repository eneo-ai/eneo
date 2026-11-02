import { describe, expect, it } from "vitest";
import {
  availableAssistantMcpServers,
  enabledMcpToolCount,
  ensureSelectedMcpToolsTracked,
  isMcpToolEnabled,
  selectedMcpServers,
  setMcpServerToolsEnabled,
  toggleMcpServerSelection,
  toggleMcpToolSelection,
  type AssistantMcpServer
} from "./mcp-tool-selection";

const server: AssistantMcpServer = {
  id: "server-1",
  name: "Search",
  tools: [
    { id: "tool-1", name: "query", is_enabled: true },
    { id: "tool-2", name: "crawl", is_enabled: false }
  ]
};

describe("MCP tool selection", () => {
  it("adds a server with every tool enabled for assistant convenience", () => {
    const next = toggleMcpServerSelection(new Set(), [], server);
    expect([...next.selectedIds]).toEqual(["server-1"]);
    expect(next.settings).toEqual([
      { tool_id: "tool-1", is_enabled: true },
      { tool_id: "tool-2", is_enabled: true }
    ]);
  });

  it("removes a server and its tool overrides", () => {
    const next = toggleMcpServerSelection(
      new Set(["server-1"]),
      [
        { tool_id: "tool-1", is_enabled: true },
        { tool_id: "tool-2", is_enabled: false },
        { tool_id: "other", is_enabled: true }
      ],
      server
    );
    expect([...next.selectedIds]).toEqual([]);
    expect(next.settings).toEqual([{ tool_id: "other", is_enabled: true }]);
  });

  it("tracks missing selected-server tools before toggling one tool", () => {
    const selected = selectedMcpServers([server], new Set(["server-1"]));
    const tracked = ensureSelectedMcpToolsTracked(selected, []);
    expect(tracked).toEqual([
      { tool_id: "tool-1", is_enabled: true },
      { tool_id: "tool-2", is_enabled: false }
    ]);

    const toggled = toggleMcpToolSelection(selected, [], "tool-1");
    expect(toggled).toEqual([
      { tool_id: "tool-1", is_enabled: false },
      { tool_id: "tool-2", is_enabled: false }
    ]);
  });

  it("applies all-on/all-off settings per server", () => {
    const selected = [server];
    const allOff = setMcpServerToolsEnabled(selected, [], server, false);
    expect(allOff).toEqual([
      { tool_id: "tool-1", is_enabled: false },
      { tool_id: "tool-2", is_enabled: false }
    ]);
    expect(isMcpToolEnabled(server, "tool-1", allOff)).toBe(false);
    expect(enabledMcpToolCount(server, allOff)).toBe(0);
  });

  it("offers the space's enabled tools and keeps a deactivated server the assistant still has", () => {
    const offered: AssistantMcpServer[] = [
      {
        ...server,
        tools: [...server.tools!, { id: "tool-3", name: "gone", removed_from_remote: true }]
      }
    ];
    const deactivated: AssistantMcpServer = {
      id: "server-2",
      name: "Arkiv",
      is_enabled: false,
      tools: [{ id: "tool-4", name: "lookup", is_enabled: false }]
    };
    const attached = [
      { ...server, is_enabled: false },
      deactivated,
      { ...deactivated, id: "x", is_enabled: true }
    ];
    expect(availableAssistantMcpServers(offered, attached)).toEqual([
      { ...server, tools: [server.tools![0]] },
      deactivated
    ]);
  });
});
