import { describe, expect, it } from "vitest";
import {
  pruneUnknownMcpServerIds,
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

describe("pruneUnknownMcpServerIds", () => {
  it("drops selected ids that no longer exist in the server catalog", () => {
    expect(pruneUnknownMcpServerIds(["enabled", "deleted"], ["enabled"])).toEqual(["enabled"]);
  });
});
