import { describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import {
  effectiveAssistantModels,
  isMcpEnforced,
  isModelsEnforced,
  isPromptLocked,
  lockedAssistantModel,
  policyMcpServers
} from "./effective-config";

function model(id: string, name: string): Schema<"CompletionModelSparse"> {
  return {
    id,
    name,
    max_input_tokens: 0,
    max_output_tokens: 0,
    is_deprecated: false,
    vision: false,
    reasoning: false,
    token_limit: 0,
    supported_model_kwargs: {}
  };
}

function mcpServer(id: string, name: string): Schema<"MCPServerPublicDict"> {
  return {
    id,
    name,
    description: null,
    http_url: null,
    http_auth_type: null,
    tags: null,
    icon_url: null,
    security_classification: null,
    tools: []
  };
}

const models = [model("a", "Alpha"), model("b", "Beta"), model("c", "Gamma")];

describe("effective assistant config", () => {
  it("leaves models unchanged when policy is not enforced", () => {
    expect(effectiveAssistantModels(models, null)).toBe(models);
  });

  it("filters models to the policy allow-list when enforced", () => {
    expect(
      effectiveAssistantModels(models, {
        models_enforced: true,
        available_models: [model("b", "Beta")],
        locked_model: null,
        default_model: null,
        mcp_enforced: false,
        available_mcp_servers: [],
        default_disabled_mcp_server_ids: [],
        prompt_locked: false
      }).map((model) => model.id)
    ).toEqual(["b"]);
  });

  it("prefers the full locked model from the space list", () => {
    const locked = lockedAssistantModel(models, {
      models_enforced: true,
      available_models: [],
      locked_model: model("c", "Sparse Gamma"),
      default_model: null,
      mcp_enforced: false,
      available_mcp_servers: [],
      default_disabled_mcp_server_ids: [],
      prompt_locked: false
    });
    expect(locked).toEqual(model("c", "Gamma"));
  });

  it("exposes policy lock booleans and MCP servers", () => {
    const config = {
      models_enforced: true,
      available_models: [],
      locked_model: null,
      default_model: null,
      mcp_enforced: true,
      available_mcp_servers: [mcpServer("server-1", "Search")],
      default_disabled_mcp_server_ids: [],
      prompt_locked: true
    };
    expect(isModelsEnforced(config)).toBe(true);
    expect(isPromptLocked(config)).toBe(true);
    expect(isMcpEnforced(config)).toBe(true);
    expect(policyMcpServers(config)).toEqual([mcpServer("server-1", "Search")]);
  });
});
