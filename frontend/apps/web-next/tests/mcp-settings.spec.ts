import { expect, test } from "./csp";
import { sessionResponseHeaders } from "./helpers";
import type { McpServer } from "../src/features/admin/mcp/mcp";

function serverFixture(overrides: Partial<McpServer> = {}): McpServer {
  return {
    id: "fixture-source",
    mcp_server_id: "fixture-source",
    name: "Fixture source",
    description: "Fixture MCP settings",
    http_url: "https://fixture.example/mcp",
    http_auth_type: "api_key_header",
    purpose: "general",
    audience: "everyone",
    audience_priority: 100,
    user_groups: [],
    has_credentials: true,
    credential_preview: "…test",
    tags: [],
    icon_url: null,
    documentation_url: null,
    security_classification: null,
    is_org_enabled: true,
    is_enabled: true,
    tools_count: 0,
    is_available: true,
    ...overrides
  };
}

test("creates a header-auth server with safe transport, identity and catalog settings", async ({
  page
}) => {
  let server: McpServer | null = null;
  const writes: unknown[] = [];
  await page.route("**/api/v1/mcp-servers/settings/", (route) =>
    route.fulfill({
      json: { items: server ? [server] : [], count: server ? 1 : 0 },
      headers: sessionResponseHeaders(route)
    })
  );
  await page.route("**/api/v1/mcp-servers/fixture-source/tools/", (route) =>
    route.fulfill({ json: { items: [], count: 0 }, headers: sessionResponseHeaders(route) })
  );
  await page.route("**/api/v1/mcp-servers/", (route) => {
    const body = route.request().postDataJSON();
    writes.push(body);
    server = serverFixture({ name: body.name, forward_identity: body.forward_identity });
    return route.fulfill({
      json: { server, connection: { tools_discovered: 0 } },
      headers: sessionResponseHeaders(route)
    });
  });
  await page.goto("/admin/tools?tab=mcp-servers");
  await page.getByRole("button", { name: "Lägg till MCP-server", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Lägg till MCP-server" });
  await dialog.getByLabel("Namn", { exact: true }).fill("Header fixture");
  const url = dialog.getByLabel("URL", { exact: true });
  await url.fill("http://fixture.example/mcp");
  await dialog.getByRole("combobox", { name: "Autentisering" }).click();
  await page.getByRole("option", { name: "API-nyckel i header" }).click();
  await dialog.getByLabel("Headernamn", { exact: true }).fill("X-Api-Key");
  await dialog
    .getByLabel(/^API-nyckel/)
    .and(dialog.locator("input"))
    .fill(" synthetic-key ");
  await dialog.getByLabel(/^Bekräfta API-nyckel/).fill(" synthetic-key ");
  await dialog.getByRole("button", { name: "Lägg till MCP-server", exact: true }).click();
  await expect(url).toBeFocused();
  await expect(url).toHaveAttribute("aria-invalid", "true");
  expect(writes).toEqual([]);
  await url.fill("https://fixture.example/mcp");
  await dialog.getByLabel("Vidarebefordra användaridentitet").check();
  await expect(dialog.getByText(/Aktivera endast för servrar du litar på/)).toBeVisible();
  await dialog.getByText("Gränser för verktygskatalogen", { exact: true }).click();
  await dialog.getByLabel("Maximal katalogstorlek (MiB)").fill("32");
  await dialog.getByRole("button", { name: "Lägg till MCP-server", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/mcp-servers\/fixture-source$/);
  await expect(page.getByRole("heading", { name: "Header fixture", level: 1 })).toBeVisible();
  expect(writes).toEqual([
    expect.objectContaining({
      http_auth_type: "api_key_header",
      http_auth_config_schema: { header_name: "X-Api-Key", token: " synthetic-key " },
      forward_identity: true,
      tool_catalog_max_count: 256,
      tool_catalog_max_bytes: 32 * 1048576,
      tool_definition_max_bytes: 64 * 1024
    })
  ]);
});

test("preserves API-header auth on token replacement and explains purpose changes before saving", async ({
  page
}) => {
  let server = serverFixture();
  const writes: unknown[] = [];
  await page.route("**/api/v1/mcp-servers/settings/", (route) =>
    route.fulfill({ json: { items: [server], count: 1 }, headers: sessionResponseHeaders(route) })
  );
  await page.route("**/api/v1/mcp-servers/fixture-source/tools/", (route) =>
    route.fulfill({ json: { items: [], count: 0 }, headers: sessionResponseHeaders(route) })
  );
  await page.route("**/api/v1/mcp-servers/fixture-source/", (route) => {
    const body = route.request().postDataJSON();
    writes.push(body);
    if (body.purpose) server = { ...server, purpose: body.purpose, is_enabled: false };
    return route.fulfill({ json: server, headers: sessionResponseHeaders(route) });
  });
  await page.goto("/admin/mcp-servers/fixture-source?tab=credentials");
  await expect(page.getByRole("combobox", { name: "Autentisering" })).toHaveText(
    "API-nyckel i header"
  );
  await page.getByRole("button", { name: "Byt token" }).click();
  await page
    .getByLabel(/^API-nyckel/)
    .and(page.locator("input"))
    .fill("synthetic-replacement");
  await page.getByLabel(/^Bekräfta API-nyckel/).fill("synthetic-replacement");
  await page.getByRole("button", { name: "Spara", exact: true }).click();
  await expect(page.getByRole("button", { name: "Byt token" })).toBeFocused();
  expect(writes).toEqual([
    {
      http_auth_type: "api_key_header",
      http_auth_config_schema: { token: "synthetic-replacement" }
    }
  ]);
  await page.getByRole("tab", { name: "Översikt" }).click();
  await page.getByLabel("Funktion", { exact: true }).selectOption("web_search");
  await expect(page.getByText(/inaktiv tills du aktiverar/)).toBeVisible();
  expect(writes).toHaveLength(1);
  await page.getByRole("button", { name: "Spara", exact: true }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toEqual({ purpose: "web_search" });
});

test.describe("image source on a touch screen", () => {
  test.use({ viewport: { width: 320, height: 740 }, hasTouch: true, isMobile: true });
  test("keeps the source draft and focus when its model wizard is cancelled", async ({ page }) => {
    const model = {
      id: "image-fixture",
      name: "fixture-image",
      nickname: "Fixture image",
      is_org_enabled: true,
      is_deprecated: false,
      provider_id: "provider-fixture",
      provider_name: "Fixture provider",
      default_size: "1536x1024",
      default_quality: "high"
    };
    const server = serverFixture({
      http_auth_type: "internal",
      has_credentials: false,
      credential_preview: null,
      purpose: "image_generation",
      image_model_id: model.id,
      is_enabled: false,
      readiness_reason: "model_disabled"
    });
    await page.route("**/api/v1/mcp-servers/settings/", (route) =>
      route.fulfill({ json: { items: [server], count: 1 }, headers: sessionResponseHeaders(route) })
    );
    await page.route("**/api/v1/image-models/", (route) =>
      route.fulfill({ json: { items: [model], count: 1 }, headers: sessionResponseHeaders(route) })
    );
    await page.route("**/api/v1/admin/model-providers/", (route) =>
      route.fulfill({
        json: [
          {
            id: "provider-fixture",
            name: "Fixture provider",
            provider_type: "openai",
            is_active: true
          }
        ],
        headers: sessionResponseHeaders(route)
      })
    );
    await page.route("**/api/v1/admin/model-providers/capabilities/", (route) =>
      route.fulfill({
        json: {
          providers: { openai: { modes: ["image"], fields: [], models: {} } },
          default_fields: []
        },
        headers: sessionResponseHeaders(route)
      })
    );
    await page.goto("/admin/tools");
    await page.getByRole("button", { name: "Ändra", exact: true }).click();
    const sourceDialog = page.getByRole("dialog", { name: /Ändra.*Bildgenerering/ });
    await sourceDialog.getByLabel("Namn", { exact: true }).fill("Touch draft");
    await expect(sourceDialog.getByText(/1536x1024/)).toBeVisible();
    await expect(sourceDialog.getByText("Bildmodellen är inaktiverad.")).toBeVisible();
    const add = sourceDialog.getByRole("button", { name: "Lägg till bildmodell" });
    await add.focus();
    await add.click();
    await expect(page.getByRole("dialog", { name: "Lägg till modell" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Lägg till modell" })).not.toBeVisible();
    await expect(sourceDialog).toBeVisible();
    await expect(sourceDialog.getByLabel("Namn", { exact: true })).toHaveValue("Touch draft");
    await expect(add).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true
    );
    await sourceDialog.screenshot({ path: test.info().outputPath("mcp-image-source-touch.png") });
  });
});
