import { describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import type { ChatPartner } from "@/lib/chat/types";
import {
  activeMcpServerCount,
  chatPartnerMcpServers,
  defaultDisabledMcpServerIds,
  mcpConversationOptions,
  pruneDisabledMcpServerIds
} from "./mcp-controls";

const server = (id: string, name = id): Schema<"MCPServerPublicDict"> => ({
  id,
  name,
  description: null,
  http_url: null,
  http_auth_type: null,
  tags: null,
  icon_url: null,
  security_classification: null,
  tools: []
});

const basePartner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Assistant"
};

describe("MCP chat controls", () => {
  it("uses governance MCP servers when the policy enforces MCP", () => {
    const policyServer = server("policy");
    const partner: ChatPartner = {
      ...basePartner,
      mcpServers: [server("assistant")],
      effectiveConfig: {
        mcp_enforced: true,
        available_mcp_servers: [policyServer],
        default_disabled_mcp_server_ids: ["policy"],
        models_enforced: false,
        available_models: [],
        locked_model: null,
        default_model: null,
        prompt_locked: false
      }
    };

    expect(chatPartnerMcpServers(partner)).toEqual([policyServer]);
    expect(defaultDisabledMcpServerIds(partner)).toEqual(["policy"]);
  });

  it("falls back to the partner MCP servers when MCP is not enforced", () => {
    const assistantServer = server("assistant");
    const partner: ChatPartner = {
      ...basePartner,
      mcpServers: [assistantServer],
      effectiveConfig: {
        mcp_enforced: false,
        available_mcp_servers: [server("policy")],
        default_disabled_mcp_server_ids: [],
        models_enforced: false,
        available_models: [],
        locked_model: null,
        default_model: null,
        prompt_locked: false
      }
    };

    expect(chatPartnerMcpServers(partner)).toEqual([assistantServer]);
  });

  it("prunes disabled ids to available servers and counts active servers", () => {
    const servers = [server("a"), server("b")];
    const disabled = pruneDisabledMcpServerIds(new Set(["a", "missing"]), servers);

    expect([...disabled]).toEqual(["a"]);
    expect(activeMcpServerCount(servers, disabled)).toBe(1);
  });

  it("builds conversation MCP request options from auto-accept and disabled servers", () => {
    const servers = [server("a"), server("b")];

    expect(
      mcpConversationOptions({
        servers,
        disabledServerIds: new Set(["a", "missing"]),
        autoAcceptTools: false,
        supportsToolApproval: true
      })
    ).toEqual({
      require_tool_approval: true,
      disabled_mcp_server_ids: ["a"]
    });

    expect(
      mcpConversationOptions({
        servers,
        disabledServerIds: new Set(),
        autoAcceptTools: true,
        supportsToolApproval: true
      })
    ).toEqual({
      require_tool_approval: undefined,
      disabled_mcp_server_ids: undefined
    });
  });

  it("does not request tool approval for partners that do not support it", () => {
    expect(
      mcpConversationOptions({
        servers: [server("a")],
        disabledServerIds: new Set(),
        autoAcceptTools: false,
        supportsToolApproval: false
      }).require_tool_approval
    ).toBeUndefined();
  });
});
