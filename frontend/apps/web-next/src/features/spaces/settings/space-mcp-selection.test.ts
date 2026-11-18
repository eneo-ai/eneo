import { describe, expect, it } from "vitest";
import {
  spaceMcpSelection,
  setSpaceMcpServer,
  setSpaceMcpTool,
  selectedVisibleMcpServerCount,
  visibleSpaceMcpServers
} from "./space-mcp-selection";

const servers = [
  { id: "enabled", is_available: true },
  { id: "disabled-selected", is_available: false },
  { id: "disabled-hidden", is_available: false }
];

describe("visibleSpaceMcpServers", () => {
  it("shows available servers and already-selected unavailable servers", () => {
    expect(
      visibleSpaceMcpServers(servers, ["disabled-selected"]).map((server) => server.id)
    ).toEqual(["enabled", "disabled-selected"]);
  });
});

describe("selectedVisibleMcpServerCount", () => {
  it("counts selected servers that are visible in the current picker", () => {
    const visible = visibleSpaceMcpServers(servers, ["disabled-selected"]);

    expect(selectedVisibleMcpServerCount(visible, ["enabled", "disabled-selected"])).toBe(2);
  });
});

describe("space MCP selection", () => {
  it("reads saved tool flags, preserving explicit off independently of catalog defaults", () => {
    expect(
      spaceMcpSelection([
        {
          id: "saved",
          name: "Saved",
          tools: [
            { id: "off", name: "Off", is_enabled: false, is_enabled_by_default: true },
            { id: "on", name: "On", is_enabled: true },
            { id: "unknown", name: "Unknown", is_enabled_by_default: true }
          ]
        }
      ])
    ).toEqual({
      serverIds: ["saved"],
      tools: [
        { tool_id: "off", is_enabled: false },
        { tool_id: "on", is_enabled: true },
        { tool_id: "unknown", is_enabled: false }
      ]
    });
  });

  it("adds all new server tools atomically without losing another saved unavailable server", () => {
    const saved = spaceMcpSelection([
      {
        id: "missing",
        name: "Missing",
        tools: [{ id: "old", name: "Old", is_enabled: false }]
      }
    ]);
    const next = setSpaceMcpServer(
      saved,
      {
        id: "new",
        name: "New",
        tools: [
          { id: "first", name: "First", is_enabled_by_default: false },
          { id: "second", name: "Second", is_enabled_by_default: false }
        ]
      },
      true
    );
    expect(next).toEqual({
      serverIds: ["missing", "new"],
      tools: [
        { tool_id: "old", is_enabled: false },
        { tool_id: "first", is_enabled: true },
        { tool_id: "second", is_enabled: true }
      ]
    });
    expect(setSpaceMcpTool(next, "first", false).tools).toEqual([
      { tool_id: "old", is_enabled: false },
      { tool_id: "first", is_enabled: false },
      { tool_id: "second", is_enabled: true }
    ]);
    expect(
      setSpaceMcpServer(
        next,
        {
          id: "new",
          name: "New",
          tools: [
            { id: "first", name: "First" },
            { id: "second", name: "Second" }
          ]
        },
        false
      )
    ).toEqual(saved);
  });
});
