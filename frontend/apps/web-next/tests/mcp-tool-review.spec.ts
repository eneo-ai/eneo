import type { Route } from "@playwright/test";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { sessionResponseHeaders } from "./helpers";

const serverId = "mcp-review-fixture";
const baseTool: Schema<"MCPServerToolPublic"> = {
  id: "records",
  mcp_server_id: serverId,
  name: "read_records",
  title: "Records",
  description: "Reads records",
  input_schema: {},
  is_enabled_by_default: true
};

async function reply(route: Route, data: unknown) {
  await route.fulfill({ json: data, headers: sessionResponseHeaders(route) });
}

test("reviews MCP view permissions and edits display names through the production UI", async ({
  page
}) => {
  let active = { ...baseTool };
  let internal = false;
  await page.route("**/api/v1/mcp-servers/settings/", (route) =>
    reply(route, {
      items: [
        {
          id: serverId,
          name: "Review server",
          description: null,
          http_url: null,
          icon_url: null,
          tags: [],
          tools: [],
          tools_count: 2,
          is_org_enabled: true,
          is_enabled: true,
          security_classification: null,
          http_auth_type: internal ? "internal" : "none",
          purpose: internal ? "image_generation" : "general"
        }
      ]
    })
  );
  await page.route(`**/api/v1/mcp-servers/${serverId}/tools/`, (route) =>
    reply(route, {
      items: internal
        ? [{ ...baseTool, name: "generate_image" }]
        : [
            active,
            {
              ...baseTool,
              id: "view",
              name: "show_records",
              requires_approval: true,
              pending_input_schema: { type: "object", required: ["query"] },
              pending_ui_resource_sha256: "pending-view",
              pending_meta: { ui: { resourceUri: "ui://records/view.html" } }
            }
          ]
    })
  );
  await page.route(`**/api/v1/mcp-servers/${serverId}/tools/view/view/`, (route) =>
    reply(route, {
      uri: "ui://records/view.html",
      pending: true,
      size_bytes: 2048,
      connect_domains: ["https://data.example"],
      resource_domains: ["https://cdn.example"],
      frame_domains: ["https://frame.example"],
      permissions: []
    })
  );
  await page.route(`**/api/v1/mcp-servers/${serverId}/tools/records/display-name/`, (route) => {
    expect(route.request().method()).toBe("PUT");
    const body: Schema<"MCPServerToolRename"> = route.request().postDataJSON();
    active = { ...active, display_name: body.display_name };
    return reply(route, active);
  });
  await page.goto(`/admin/mcp-servers/${serverId}?tab=tools`);
  const panel = page.getByRole("tabpanel", { name: "MCP-serververktyg" });
  await expect(panel.getByText("ui://records/view.html", { exact: true })).toBeVisible();
  for (const domain of ["https://data.example", "https://cdn.example", "https://frame.example"]) {
    await expect(panel.getByText(domain, { exact: true })).toBeVisible();
  }
  await expect(panel.getByText("Ändrad", { exact: true })).toBeVisible();
  const rename = panel.getByRole("button", { name: /Byt visningsnamn/ });
  await rename.focus();
  await page.keyboard.press("Enter");
  const input = panel.getByRole("textbox", { name: "Visningsnamn", exact: true });
  await expect(input).toBeFocused();
  await input.fill("  Local records  ");
  await input.press("Enter");
  await expect(panel.getByText("Local records", { exact: true })).toBeVisible();
  await expect(panel.getByText("read_records", { exact: true })).toBeVisible();
  await rename.click();
  await input.fill("");
  await input.press("Enter");
  await expect(panel.getByText("Records", { exact: true })).toBeVisible();
  await expect(panel.locator("iframe")).toHaveCount(0);
  await panel.screenshot({ path: test.info().outputPath("mcp-tool-review.png") });
  internal = true;
  await page.reload();
  await expect(panel.getByText("Generera bild", { exact: true })).toBeVisible();
  await expect(panel.getByRole("switch")).toHaveCount(0);
  await expect(
    panel.getByRole("button", { name: /Synkronisera|Byt visningsnamn|Alla på|Alla av/ })
  ).toHaveCount(0);
});
