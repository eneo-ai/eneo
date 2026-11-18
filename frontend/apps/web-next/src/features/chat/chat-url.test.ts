import { describe, expect, it } from "vitest";
import { readChatTab } from "./chat-url";

describe("readChatTab", () => {
  // Svelte's chat page: ?tab=chat|history|insights, Chatt by default.
  it.each([
    ["", "chat"],
    ["tab=chat", "chat"],
    ["tab=history", "history"],
    ["tab=insights", "insights"],
    ["tab=other", "chat"]
  ])("reads %s as %s", (query, tab) => {
    expect(readChatTab(new URLSearchParams(query))).toBe(tab);
  });
});
