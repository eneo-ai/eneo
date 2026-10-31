import { expect, test } from "./csp";
import { sessionResponseHeaders } from "./helpers";

test("activates a function source from the MCP list and explains a refusal", async ({ page }) => {
  const previous = {
    id: "previous",
    name: "Previous source",
    description: "Earlier images",
    purpose: "image_generation",
    http_url: "https://previous.example/mcp",
    http_auth_type: "none",
    icon_url: null,
    tags: [],
    tools: [],
    tools_count: 1,
    is_org_enabled: true,
    is_enabled: true,
    security_classification: null
  };
  const preferred = {
    ...previous,
    id: "preferred",
    name: "Preferred source",
    description: "Illustrationer",
    http_url: "https://preferred.example/mcp",
    http_auth_type: "api_key_header",
    is_enabled: false,
    audience: "everyone",
    user_groups: [],
    forward_identity: true
  };
  let refused = true;
  await page.route("**/api/v1/mcp-servers/settings/", (route) =>
    route.fulfill({
      json: { items: [previous, preferred] },
      headers: sessionResponseHeaders(route)
    })
  );
  await page.route("**/api/v1/mcp-servers/preferred/activate/", (route) => {
    expect(route.request().method()).toBe("POST");
    if (refused)
      return route.fulfill({
        status: 400,
        json: {
          message: "Provider has no enabled tools. Sync and approve its tools before activating.",
          eneo_error_code: 9007
        }
      });
    preferred.is_enabled = true;
    previous.is_enabled = false;
    return route.fulfill({ json: {}, headers: sessionResponseHeaders(route) });
  });
  await page.route("**/api/v1/mcp-servers/preferred/deactivate/", (route) => {
    expect(route.request().method()).toBe("POST");
    preferred.is_enabled = false;
    return route.fulfill({ json: {}, headers: sessionResponseHeaders(route) });
  });
  await page.goto("/admin/tools?tab=mcp-servers");
  await page.getByRole("switch", { name: "Visa funktionsservrar" }).click();
  const preferredSwitch = page.getByRole("switch", { name: "Aktivera Preferred source" });
  await expect(preferredSwitch).not.toBeChecked();
  await expect(page.getByText("API-nyckel i header", { exact: true })).toBeVisible();
  await preferredSwitch.focus();
  await page.keyboard.press("Space");
  await expect(page.getByRole("alert")).toContainText("Provider has no enabled tools");
  await expect(preferredSwitch).not.toBeChecked();
  await expect(preferredSwitch).toBeFocused();
  refused = false;
  await page.keyboard.press("Space");
  await expect(preferredSwitch).toBeChecked();
  await expect(page.getByRole("switch", { name: "Aktivera Previous source" })).not.toBeChecked();
  await expect(page.getByRole("alert")).toHaveCount(0);
  const search = page.getByRole("textbox", { name: "Sök MCP-servrar" });
  await search.fill("illustrationer");
  await expect(page.getByRole("link", { name: "Preferred source", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Previous source", exact: true })).toHaveCount(0);
  await search.clear();
  await preferredSwitch.click();
  await expect(preferredSwitch).not.toBeChecked();
  await page
    .getByRole("main")
    .screenshot({ path: test.info().outputPath("mcp-server-activation.png") });
});
