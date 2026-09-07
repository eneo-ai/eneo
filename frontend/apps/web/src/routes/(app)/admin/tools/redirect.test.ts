import { expect, it } from "vitest";
import { load } from "../mcp-servers/+page";
it("redirects the old MCP URL to the external connections tab", () => {
  try {
    load({} as never);
    throw new Error("Expected a redirect");
  } catch (error) {
    expect(error).toMatchObject({
      status: 307,
      location: expect.stringContaining("/admin/tools?tab=mcp-servers")
    });
  }
});
