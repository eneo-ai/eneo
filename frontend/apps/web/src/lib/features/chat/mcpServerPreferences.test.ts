import { describe, expect, it } from "vitest";
import {
  initialDisabledMcpServerIds,
  loadMcpServerPreferences,
  saveMcpServerPreferences,
  type McpServerPreferencesContext
} from "./mcpServerPreferences";

class MemoryStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}

const context: McpServerPreferencesContext = {
  tenantId: "tenant-1",
  userId: "user-1",
  assistantId: "assistant-1"
};

describe("MCP server preferences", () => {
  it("round-trips enabled and disabled server states", () => {
    const storage = new MemoryStorage();

    saveMcpServerPreferences(context, ["server-a", "server-b"], new Set(["server-b"]), storage);

    expect(loadMcpServerPreferences(context, storage)).toEqual({
      serverStates: { "server-a": true, "server-b": false }
    });
  });

  it("isolates preferences by tenant, user, and assistant", () => {
    const storage = new MemoryStorage();
    saveMcpServerPreferences(context, ["server-a"], new Set(["server-a"]), storage);

    for (const differentContext of [
      { ...context, tenantId: "tenant-2" },
      { ...context, userId: "user-2" },
      { ...context, assistantId: "assistant-2" }
    ]) {
      expect(loadMcpServerPreferences(differentContext, storage)).toBeNull();
    }
  });

  it("uses governance defaults for new servers without overriding explicit choices", () => {
    expect(
      initialDisabledMcpServerIds({
        availableServerIds: ["explicitly-on", "explicitly-off", "new-default-off"],
        defaultDisabledServerIds: ["explicitly-on", "new-default-off"],
        preferences: {
          serverStates: { "explicitly-on": true, "explicitly-off": false }
        }
      })
    ).toEqual(["explicitly-off", "new-default-off"]);
  });

  it("ignores unavailable saved servers", () => {
    expect(
      initialDisabledMcpServerIds({
        availableServerIds: ["available"],
        defaultDisabledServerIds: [],
        preferences: { serverStates: { stale: false } }
      })
    ).toEqual([]);
  });

  it("discards malformed storage instead of breaking chat", () => {
    const storage = new MemoryStorage();
    storage.values.set("eneo:chat-mcp:v1:tenant-1:user-1:assistant-1", "not-json");

    expect(loadMcpServerPreferences(context, storage)).toBeNull();
  });

  it("keeps chat usable when browser storage is unavailable", () => {
    const unavailableStorage = {
      getItem: () => {
        throw new Error("storage blocked");
      },
      setItem: () => {
        throw new Error("storage blocked");
      },
      removeItem: () => {
        throw new Error("storage blocked");
      }
    };

    expect(loadMcpServerPreferences(context, unavailableStorage)).toBeNull();
    expect(() =>
      saveMcpServerPreferences(context, ["server-a"], new Set(), unavailableStorage)
    ).not.toThrow();
  });
});
