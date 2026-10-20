import { describe, expect, it } from "vitest";
import {
  assistantMcpServersFromApi,
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
  it("parses API server tools without trusting unknown payload shape", () => {
    expect(
      assistantMcpServersFromApi([
        {
          id: "server-1",
          name: "Search",
          tools: [{ id: "tool-1", name: "query", is_enabled: true }, { id: "invalid" }]
        }
      ])
    ).toEqual([
      {
        id: "server-1",
        name: "Search",
        description: undefined,
        tools: [
          {
            id: "tool-1",
            name: "query",
            title: undefined,
            description: undefined,
            is_enabled: true,
            is_enabled_by_default: undefined,
            removed_from_remote: undefined
          }
        ]
      }
    ]);
  });

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
});
