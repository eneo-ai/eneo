import { describe, expect, it } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import {
  chatCapabilities,
  defaultDisabledCapabilities,
  disabledCapabilitiesForRequest
} from "./chat-capabilities";

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
  it("shows configured functions with availability and respects role permissions", () => {
    expect(chatCapabilities(partner, (purpose) => purpose === "image_generation")).toEqual([
      { purpose: "image_generation", available: false, reason: "no_active_provider" }
    ]);
  });

  it("uses enforced policy and its default-off settings instead of assistant choices", () => {
    const governed: ChatPartner = {
      ...partner,
      effectiveConfig: {
        models_enforced: false,
        available_models: [],
        locked_model: null,
        default_model: null,
        mcp_enforced: true,
        available_mcp_servers: [],
        default_disabled_mcp_server_ids: [],
        prompt_locked: false,
        default_reasoning_effort: null,
        reasoning_effort_user_configurable: false,
        enabled_capabilities: ["image_generation"],
        available_capabilities: [{ purpose: "image_generation", available: true, reason: null }],
        default_disabled_capabilities: ["image_generation"]
      }
    };
    expect(chatCapabilities(governed, () => true)).toEqual([
      { purpose: "image_generation", available: true, reason: null }
    ]);
    expect(defaultDisabledCapabilities(governed)).toEqual(["image_generation"]);
  });

  it("keeps assistant functions when governance does not enforce MCP", () => {
    const ungoverned: ChatPartner = {
      ...partner,
      effectiveConfig: {
        models_enforced: false,
        available_models: [],
        locked_model: null,
        default_model: null,
        mcp_enforced: false,
        available_mcp_servers: [],
        default_disabled_mcp_server_ids: [],
        prompt_locked: false,
        default_reasoning_effort: null,
        reasoning_effort_user_configurable: false,
        enabled_capabilities: []
      }
    };
    expect(chatCapabilities(ungoverned, () => true).map((item) => item.purpose)).toEqual([
      "web_search",
      "image_generation"
    ]);
  });

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
