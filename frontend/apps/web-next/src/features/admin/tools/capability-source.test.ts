import { describe, expect, it } from "vitest";
import type { McpServer } from "@/features/admin/mcp/mcp";
import {
  createSourcePayload,
  sourceDraft,
  sourceDraftProblems,
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

describe("sourceDraftProblems", () => {
  it("requires the API key again when replacing a saved header name", () => {
    const server = { ...external, http_auth_type: "api_key_header" };
    const draft = { ...sourceDraft(server), headerName: "X-Replacement" };
    expect(sourceDraftProblems(draft, server)).toEqual([{ field: "token", kind: "required" }]);
  });
  it("refuses a remote HTTP URL carrying a credential, but identity forwarding alone is allowed", () => {
    const draft = { ...sourceDraft(external), url: "http://remote.example/mcp" };
    expect(sourceDraftProblems(draft, external)).toContainEqual({
      field: "url",
      kind: "credential-transport"
    });
    expect(
      sourceDraftProblems({ ...draft, auth: "none", forwardIdentity: true }, external)
    ).toEqual([]);
    expect(
      sourceDraftProblems(
        { ...draft, auth: "none", url: "http://user@remote.example/mcp" },
        external
      )
    ).toContainEqual({ field: "url", kind: "credential-transport" });
  });

  it("lists the problems in the order of the form's fields", () => {
    const draft = {
      ...sourceDraft(),
      auth: "api_key_header" as const,
      audience: "groups" as const,
      priority: -1
    };
    expect(sourceDraftProblems(draft).map((problem) => problem.field)).toEqual([
      "url",
      "headerName",
      "token",
      "name",
      "groups",
      "priority"
    ]);
  });

  it("lets a saved credential be left empty", () => {
    const draft = { ...sourceDraft(external), token: "" };
    expect(sourceDraftProblems(draft, external)).toEqual([]);
    // Another kind of credential than the saved one needs its own.
    expect(sourceDraftProblems({ ...draft, auth: "api_key_header" }, external)).toEqual([
      { field: "headerName", kind: "required" },
      { field: "token", kind: "required" }
    ]);
  });
});

describe("capability source payloads", () => {
  it("preserves secret bytes, omits blank saved secrets and lets the backend refuse control characters", () => {
    const server = { ...external, http_auth_type: "api_key_header" };
    const draft = sourceDraft(server);
    expect(
      updateSourcePayload(server, { ...draft, token: " synthetic-key " }).http_auth_config_schema
    ).toEqual({ token: " synthetic-key " });
    expect(
      updateSourcePayload(server, { ...draft, token: "   " }).http_auth_config_schema
    ).toBeUndefined();
    expect(
      updateSourcePayload(server, { ...draft, token: "synthetic\n" }).http_auth_config_schema
    ).toEqual({ token: "synthetic\n" });
    expect(
      createSourcePayload("web_search", {
        ...draft,
        token: " synthetic-key ",
        headerName: " X-Api-Key "
      }).http_auth_config_schema
    ).toEqual({ token: " synthetic-key ", header_name: "X-Api-Key" });
  });
  it("keeps API-header metadata edits credential-free and supports a token-only replacement", () => {
    const server = { ...external, http_auth_type: "api_key_header" };
    const draft = sourceDraft(server);
    expect(updateSourcePayload(server, draft).http_auth_config_schema).toBeUndefined();
    expect(
      updateSourcePayload(server, { ...draft, token: "synthetic-key" }).http_auth_config_schema
    ).toEqual({ token: "synthetic-key" });
    expect(
      updateSourcePayload(server, { ...draft, token: "synthetic-key", headerName: "X-Replacement" })
        .http_auth_config_schema
    ).toEqual({ header_name: "X-Replacement", token: "synthetic-key" });
  });

  it.each([
    ["toolCatalogMaxCount", 4097],
    ["toolCatalogMaxMiB", 65],
    ["toolDefinitionMaxKiB", 1025]
  ] as const)("refuses a catalog %s beyond its backend bound", (field, value) => {
    expect(sourceDraftProblems({ ...sourceDraft(external), [field]: value }, external)).toEqual([
      expect.objectContaining({ field, kind: "whole-number" })
    ]);
  });
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
    expect(sourceDraftProblems(draft)).toEqual([]);
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
    expect(sourceDraftProblems({ ...draft, imageModelId: "" })).toEqual([
      { field: "imageModel", kind: "required" }
    ]);
    expect(sourceDraftProblems({ ...draft, toolCatalogMaxCount: 4097 })).toEqual([
      { field: "toolCatalogMaxCount", kind: "whole-number", min: 1, max: 4096 }
    ]);
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
