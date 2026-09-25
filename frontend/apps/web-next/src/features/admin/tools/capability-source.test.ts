import { describe, expect, it } from "vitest";
import type { McpServer } from "@/features/admin/mcp/mcp";
import {
  createSourcePayload,
  sourceDraft,
  sourceDraftValid,
  updateSourcePayload
} from "./capability-source";

const external: McpServer = {
  id: "server",
  mcp_server_id: "server",
  name: "Search",
  description: "",
  http_url: "https://old.example/mcp",
  http_auth_type: "bearer",
  purpose: "web_search",
  audience: "everyone",
  audience_priority: 100,
  user_groups: [],
  forward_identity: false,
  documentation_url: null,
  security_classification: null,
  has_credentials: true,
  tags: null,
  icon_url: null,
  is_org_enabled: true,
  tools_count: 0,
  is_available: true
};

describe("capability source payloads", () => {
  it("creates an external source inactive with its audience and credentials", () => {
    const draft = {
      ...sourceDraft(),
      name: "Search",
      url: "https://new.example/mcp",
      auth: "bearer" as const,
      token: "secret",
      audience: "groups" as const,
      groupIds: ["group"]
    };
    expect(sourceDraftValid(draft)).toBe(true);
    const payload = createSourcePayload("web_search", draft);
    expect(payload).toMatchObject({
      purpose: "web_search",
      http_auth_type: "bearer",
      http_auth_config_schema: { token: "secret" },
      audience: "groups",
      user_group_ids: ["group"]
    });
    expect(payload.activate).toBeUndefined();
  });

  it("activates a built-in image model on creation", () => {
    const draft = {
      ...sourceDraft(),
      name: "Images",
      source: "builtin" as const,
      imageModelId: "model"
    };
    expect(createSourcePayload("image_generation", draft)).toMatchObject({
      http_auth_type: "internal",
      image_model_id: "model",
      activate: true
    });
    expect(sourceDraftValid({ ...draft, imageModelId: "" })).toBe(false);
    expect(sourceDraftValid({ ...draft, toolCatalogMaxCount: 4097 })).toBe(false);
  });

  it("preserves credentials and connection on metadata-only edits", () => {
    const draft = { ...sourceDraft(external), description: "Updated" };
    const payload = updateSourcePayload(external, draft);
    expect(payload).toMatchObject({ description: "Updated" });
    expect(payload.http_url).toBeUndefined();
    expect(payload.http_auth_type).toBeUndefined();
    expect(payload.http_auth_config_schema).toBeUndefined();
  });
});
