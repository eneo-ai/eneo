import type { Page } from "@playwright/test";
import type { Schema } from "../src/lib/api/models";
import messages from "../src/lib/i18n/messages/sv.json";
import { expect, test } from "./csp";
import { sessionResponseHeaders } from "./helpers";

async function policyFixtures(page: Page, filesEnabled: boolean) {
  await page.route("**/api/v1/settings/", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    const settings: Schema<"SettingsPublic"> = await response.json();
    await route.fulfill({
      json: { ...settings, file_references_enabled: filesEnabled },
      headers: sessionResponseHeaders(route)
    });
  });
  await page.route("**/api/v1/ai-models/", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    const models: Schema<"ModelsPresentation"> = await response.json();
    expect(models.completion_models.length).toBeGreaterThan(0);
    await route.fulfill({
      json: {
        ...models,
        completion_models: models.completion_models.map((model) => ({
          ...model,
          can_access: true,
          supported_model_kwargs: {
            reasoning_effort: { supported: true, control: "select", options: ["low", "high"] }
          }
        }))
      },
      headers: sessionResponseHeaders(route)
    });
  });
  const general: Schema<"MCPServerSettingsPublic"> = {
    id: "general-fixture",
    mcp_server_id: "general-fixture",
    name: "General fixture",
    description: null,
    http_url: "https://example.org/mcp",
    http_auth_type: "none",
    purpose: "general",
    is_enabled: true,
    has_credentials: false,
    tags: null,
    icon_url: null,
    documentation_url: null,
    is_org_enabled: true,
    tools: [],
    tools_count: 0,
    is_available: true
  };
  const servers: Schema<"MCPServerSettingsPublic">[] = [
    general,
    { ...general, id: "search-one", mcp_server_id: "search-one", purpose: "web_search" },
    { ...general, id: "search-two", mcp_server_id: "search-two", purpose: "web_search" }
  ];
  await page.route("**/api/v1/mcp-servers/settings/", (route) =>
    route.fulfill({
      json: { items: servers, count: servers.length },
      headers: sessionResponseHeaders(route)
    })
  );
  const policy: Schema<"GovernancePolicyPublic"> = {
    models_restriction: { enabled: false, models: [], provider_ids: [] },
    mcp_restriction: {
      enabled: true,
      servers: [{ mcp_server_id: general.id, is_default_enabled: true }],
      capabilities: [{ purpose: "web_search", is_default_enabled: true }],
      disabled_tool_ids: []
    },
    prompt_enforcement: { enabled: false, prompt_library_id: null },
    reasoning_policy: { configured: true, default_effort: "high", allow_user_override: false },
    file_policy: { configured: true, inline_file_text: false },
    skills: { bindings: [] },
    updated_at: null,
    updated_by_user_id: null
  };
  await page.route("**/api/v1/admin/governance-policy/", (route) =>
    route.fulfill({
      json: policy,
      headers: sessionResponseHeaders(route)
    })
  );
}

for (const enabled of [false, true]) {
  test(
    `governance honors file references ${enabled} with localized summaries`,
    { tag: "@vite" },
    async ({ page }, testInfo) => {
      await policyFixtures(page, enabled);
      await page.goto("/admin/personal-assistant");
      await expect(
        page.getByRole("heading", { level: 1, name: messages.governance_title, exact: true })
      ).toBeVisible();
      const reasoning = page.getByRole("region", {
        name: messages.governance_reasoning_heading,
        exact: true
      });
      await expect(reasoning.getByRole("combobox")).toHaveText(messages.parameter_option_high);
      await expect(
        reasoning.getByText("Hög · styrs av organisationen", { exact: true })
      ).toBeVisible();
      const mcp = page.getByRole("region", { name: messages.governance_mcp_heading, exact: true });
      await expect(mcp.getByText("Aktiv – 2 av 7", { exact: true })).toBeVisible();
      await expect(
        mcp.getByRole("switch", { name: `Tillåt ${messages.web_search}`, exact: true })
      ).toHaveCount(1);
      const files = page.getByRole("region", {
        name: messages.governance_files_heading,
        exact: true
      });
      if (!enabled) {
        await expect(files).toHaveCount(0);
        return;
      }
      await expect(
        files.getByRole("switch", { name: messages.attachments_open_files_label, exact: true })
      ).toBeChecked();
      for (const explanation of [
        messages.attachments_open_files_on,
        messages.attachments_open_files_off,
        messages.attachments_open_files_example
      ]) {
        await expect(files.getByText(explanation, { exact: false })).toBeVisible();
      }
      await page.setViewportSize({ width: 320, height: 900 });
      await page.emulateMedia({ colorScheme: "dark" });
      await files.scrollIntoViewIfNeeded();
      await files.screenshot({ path: testInfo.outputPath("file-policy-320-dark.png") });
    }
  );
}

test(
  "prompt name stops native typing at 200 characters and cancels its draft",
  { tag: "@vite" },
  async ({ page }) => {
    await page.goto("/admin/prompt-library");
    const create = page.getByRole("button", {
      name: messages.governance_prompt_create,
      exact: true
    });
    await create.click();
    const dialog = page.getByRole("dialog", {
      name: messages.governance_prompt_new_heading,
      exact: true
    });
    const name = dialog.getByRole("textbox", { name: /^Namn/ });
    await expect(name).toHaveAttribute("maxlength", "200");
    await name.pressSequentially("x".repeat(205));
    await expect(name).toHaveValue("x".repeat(200));
    await name.press("Backspace");
    await name.pressSequentially("y");
    await expect(name).toHaveValue("x".repeat(199) + "y");
    await dialog.getByRole("button", { name: messages.cancel, exact: true }).click();
    await expect(dialog).toBeHidden();
    await create.click();
    await expect(name).toHaveValue("");
    await dialog.getByRole("button", { name: messages.cancel, exact: true }).click();
  }
);
