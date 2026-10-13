import { describe, expect, it, vi } from "vitest";
import type { EneoClient } from "@/lib/api/browser";
import type { McpServer } from "./mcp";
import { setServerActivation } from "./mcp";

function setup() {
  const POST = vi.fn().mockResolvedValue({ data: {}, response: { ok: true } });
  const DELETE = vi.fn().mockResolvedValue({ data: {}, response: { ok: true } });
  return { api: { POST, DELETE } as unknown as EneoClient, POST, DELETE };
}

describe("MCP activation endpoint", () => {
  it("uses tenant settings for general servers", async () => {
    const { api, POST, DELETE } = setup();
    const server = { id: "general", purpose: "general" } as McpServer;
    await setServerActivation(api, server, true);
    await setServerActivation(api, server, false);
    expect(POST).toHaveBeenCalledWith("/api/v1/mcp-servers/settings/{mcp_server_id}/", {
      params: { path: { mcp_server_id: "general" } },
      body: {}
    });
    expect(DELETE).toHaveBeenCalledWith("/api/v1/mcp-servers/settings/{mcp_server_id}/", {
      params: { path: { mcp_server_id: "general" } }
    });
  });

  it("uses capability activation for function sources", async () => {
    const { api, POST, DELETE } = setup();
    const server = { id: "images", purpose: "image_generation" } as McpServer;
    await setServerActivation(api, server, true);
    await setServerActivation(api, server, false);
    expect(POST).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/activate/", {
      params: { path: { id: "images" } }
    });
    expect(POST).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/deactivate/", {
      params: { path: { id: "images" } }
    });
    expect(DELETE).not.toHaveBeenCalled();
  });
});
