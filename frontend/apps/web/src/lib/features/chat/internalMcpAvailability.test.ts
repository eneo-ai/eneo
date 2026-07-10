import { describe, expect, it } from "vitest";
import { effectiveKnowledgeMode, internalMcpServerNames } from "./internalMcpAvailability";

describe("internal MCP availability", () => {
  it("falls back to inject mode when the effective model cannot call tools", () => {
    expect(effectiveKnowledgeMode("tool", false)).toBe("inject");
    expect(
      internalMcpServerNames({
        supportsToolCalling: false,
        hasKnowledge: true,
        storedKnowledgeMode: "tool",
        inlineFileText: false,
        hasDownloadReference: true
      })
    ).toEqual([]);
  });

  it("lists only internal servers whose runtime gates are satisfied", () => {
    expect(
      internalMcpServerNames({
        supportsToolCalling: true,
        hasKnowledge: true,
        storedKnowledgeMode: "tool",
        inlineFileText: false,
        hasDownloadReference: true
      })
    ).toEqual(["knowledge", "files"]);

    expect(
      internalMcpServerNames({
        supportsToolCalling: true,
        hasKnowledge: false,
        storedKnowledgeMode: "inject",
        inlineFileText: false,
        hasDownloadReference: false
      })
    ).toEqual([]);
  });
});
