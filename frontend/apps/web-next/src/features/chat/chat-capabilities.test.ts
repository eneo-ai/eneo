import { describe, expect, it } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { disabledCapabilitiesForRequest } from "./chat-capabilities";

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant",
  name: "Assistant",
  enabledCapabilities: ["web_search", "image_generation"],
  availableCapabilities: [
    { purpose: "web_search", available: true, reason: null },
    { purpose: "image_generation", available: false, reason: "no_active_provider" }
  ]
};

describe("chat capability controls", () => {
  it("sends each disabled function by purpose and keeps the web search feature gate", () => {
    expect(disabledCapabilitiesForRequest(partner, new Set(["image_generation"]), true)).toEqual([
      "image_generation"
    ]);
    expect(
      disabledCapabilitiesForRequest(
        { ...partner, type: "default-assistant" },
        new Set(["image_generation"]),
        false
      )
    ).toEqual(["image_generation", "web_search"]);
    expect(disabledCapabilitiesForRequest(partner, new Set(), true)).toBeUndefined();
  });
});
