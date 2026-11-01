import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import type { Schema } from "../src/lib/api/models";
import type { Space, SpaceSparse } from "../src/features/spaces/space";
import { WCAG_22_AA_TAGS } from "../src/test/wcag";
import messages from "../src/lib/i18n/messages/sv.json";
import { expect, test } from "./csp";
import {
  apiPost,
  createSpace,
  E2E_CREDENTIALS,
  sessionResponseHeaders,
  uniqueName
} from "./helpers";

async function scan(page: Page) {
  type AxePage = ConstructorParameters<typeof AxeBuilder>[0]["page"];
  const result = await new AxeBuilder({ page: page as unknown as AxePage })
    .withTags(WCAG_22_AA_TAGS)
    .analyze();
  expect(
    result.violations.map((violation) => ({
      id: violation.id,
      nodes: violation.nodes.map((node) => node.target)
    }))
  ).toEqual([]);
}

test(
  "Edit works without Delete and settings keep real persistence and slow-delete feedback",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    const name = uniqueName("Settings navigation");
    const space = await createSpace(page, name);
    const spaceId = space.split("/").at(-1)!;
    // Only the list permission projection is a fixture; detail authorization,
    // name persistence and deletion use the real backend and browser session.
    await page.route("**/api/v1/spaces/", async (route) => {
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      const payload: Schema<"PaginatedResponse_SpaceSparse_"> = await response.json();
      await route.fulfill({
        response,
        json: {
          ...payload,
          items: payload.items.map((item: SpaceSparse) =>
            item.id === spaceId ? { ...item, permissions: ["read", "edit"] } : item
          )
        }
      });
    });
    await page.goto("/spaces/list");
    await page.getByRole("textbox", { name: "Filtrera ytor", exact: true }).fill(name);
    await page.getByRole("button", { name: `Fler åtgärder för ${name}`, exact: true }).click();
    await expect(page.getByRole("menuitem", { name: "Radera yta", exact: true })).toHaveCount(0);
    const edit = page.getByRole("menuitem", { name: "Redigera", exact: true });
    await edit.focus();
    await edit.press("Enter");
    await expect(page).toHaveURL(`${space}/settings`);
    const renamed = `${name} sparad`;
    const nameInput = page.getByRole("textbox", { name: "Namn", exact: true });
    await nameInput.fill(renamed);
    const saved = page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" &&
        new URL(response.url()).pathname === `/api/v1${space}/`
    );
    await nameInput.press("Tab");
    expect((await saved).status()).toBe(200);
    await page.reload();
    await expect(nameInput).toHaveValue(renamed);
    await scan(page);
    // Hold the browser request for the slow-operation presentation, then let
    // it continue with its original session cookie and fetch metadata.
    let deliverDelete!: () => void;
    const delivery = new Promise<void>((resolve) => {
      deliverDelete = resolve;
    });
    await page.route(`**/api/v1${space}/`, async (route) => {
      if (route.request().method() !== "DELETE") return route.continue();
      await delivery;
      await route.continue();
    });
    await page.getByRole("button", { name: "Radera denna yta", exact: true }).click();
    const dialog = page.getByRole("alertdialog", { name: "Radera yta", exact: true });
    await dialog
      .getByRole("textbox", { name: "Ange ytnamnet för att bekräfta", exact: true })
      .fill(renamed);
    const deletion = page.waitForResponse(
      (response) =>
        response.request().method() === "DELETE" &&
        new URL(response.url()).pathname === `/api/v1${space}/`
    );
    await dialog.getByRole("button", { name: "Bekräfta borttagning", exact: true }).click();
    try {
      await expect(dialog.getByText(messages.delete_space_hint, { exact: true })).toBeVisible({
        timeout: 7_000
      });
      await dialog.screenshot({ path: testInfo.outputPath("slow-space-delete.png") });
    } finally {
      deliverDelete();
    }
    expect((await deletion).status()).toBe(204);
    await expect(page).toHaveURL("/spaces/list");
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
  }
);

test(
  "settings explain presented MCP and model restrictions and confirm clear through the real PATCH",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    const space = await createSpace(page, uniqueName("Settings presentation"));
    const current: Schema<"SecurityClassificationPublic"> = {
      id: "class-current-fixture",
      name: "Intern",
      description: null,
      security_level: 2
    };
    const target: Schema<"SecurityClassificationPublic"> = {
      ...current,
      id: "class-target-fixture",
      name: "Hemlig",
      security_level: 3
    };
    const server: Schema<"MCPServerSettingsPublic"> = {
      id: "mcp-presentation",
      mcp_server_id: "mcp-presentation",
      name: "Avtalsverktyg",
      description: "Verktyg för avtalsuppföljning",
      http_url: "https://fixture.example.test/mcp",
      http_auth_type: "none",
      has_credentials: false,
      is_org_enabled: true,
      is_available: true,
      tags: ["Avtal"],
      icon_url: null,
      documentation_url: null,
      security_classification: target,
      tools_count: 1,
      tools: [
        {
          id: "tool-presentation",
          mcp_server_id: "mcp-presentation",
          name: "Läs avtal",
          description: null,
          input_schema: null,
          is_enabled_by_default: true
        }
      ]
    };
    // These GET projections exercise presentation and keyboard interaction.
    // No external MCP runs, and the impact response is deliberately synthetic.
    await page.route(`**/api/v1${space}/`, async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      const data: Space = await response.json();
      const saved: Schema<"MCPServerPublicDict"> = {
        id: server.id,
        name: server.name,
        description: server.description,
        http_url: server.http_url,
        http_auth_type: server.http_auth_type,
        purpose: "general",
        is_enabled: true,
        readiness_reason: null,
        tags: server.tags,
        icon_url: null,
        security_classification: target,
        tools: (server.tools ?? []).map((tool) => ({ ...tool, is_enabled: false }))
      };
      await route.fulfill({
        response,
        json: { ...data, security_classification: current, mcp_servers: [saved] }
      });
    });
    await page.route("**/api/v1/security-classifications/", (route) =>
      route.fulfill({
        json: { security_enabled: true, security_classifications: [current, target] },
        headers: sessionResponseHeaders(route)
      })
    );
    await page.route("**/api/v1/mcp-servers/settings/", (route) =>
      route.fulfill({
        json: {
          items: [
            server,
            {
              ...server,
              id: "blocked-fixture",
              mcp_server_id: "blocked-fixture",
              name: "Oklassad källa",
              tags: null,
              security_classification: null,
              tools: [],
              tools_count: 0
            }
          ],
          count: 2
        },
        headers: sessionResponseHeaders(route)
      })
    );
    await page.route("**/api/v1/ai-models/", async (route) => {
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      const models: Schema<"ModelsPresentation"> = await response.json();
      expect(models.completion_models.length).toBeGreaterThan(0);
      await route.fulfill({
        response,
        json: {
          ...models,
          completion_models: models.completion_models.map((model) => ({
            ...model,
            is_deprecated: true,
            deprecation_date: "2020-01-01"
          }))
        }
      });
    });
    const impact: Schema<"UpdateSpaceDryRunResponse"> = {
      assistants: [],
      group_chats: [],
      apps: [],
      services: [],
      completion_models: [],
      embedding_models: [],
      transcription_models: [],
      mcp_servers: [],
      capabilities: ["web_search"]
    };
    const impactRequests: string[] = [];
    await page.route(`**/api/v1${space}/security_classification/*/impact-analysis/`, (route) => {
      impactRequests.push(route.request().url());
      return route.fulfill({ json: impact, headers: sessionResponseHeaders(route) });
    });
    const writes: Schema<"PartialUpdateSpaceRequest">[] = [];
    page.on("request", (request) => {
      if (request.method() === "PATCH" && new URL(request.url()).pathname === `/api/v1${space}/`)
        writes.push(request.postDataJSON());
    });
    await page.goto(`${space}/settings`);
    const disclosure = page.getByRole("button", { name: "Verktyg för Avtalsverktyg", exact: true });
    await disclosure.focus();
    await disclosure.press("Enter");
    await expect(disclosure).toBeFocused();
    await expect(
      page
        .getByRole("group", { name: "Verktyg för Avtalsverktyg", exact: true })
        .getByRole("switch", { name: "Läs avtal", exact: true })
    ).not.toBeChecked();
    await expect(page.getByText("Avtal", { exact: true })).toBeVisible();
    await expect(page.getByRole("switch", { name: "Oklassad källa", exact: true })).toHaveAttribute(
      "aria-disabled",
      "true"
    );
    await page.getByRole("button", { name: "Välj Chattmodeller", exact: true }).click();
    await expect(page.getByText("Utfasad", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("2020-01-01", { exact: true }).first()).toBeVisible();
    await scan(page);
    await page.locator("#tools").screenshot({ path: testInfo.outputPath("space-mcp-tools.png") });
    const classification = page.getByRole("combobox", {
      name: "Säkerhetsklassificering",
      exact: true
    });
    await classification.click();
    await page.getByRole("option", { name: "Hemlig", exact: true }).click();
    const confirm = page.getByRole("alertdialog");
    await expect(confirm.getByText("Webbsökning", { exact: true })).toBeVisible();
    await expect(confirm.getByText("Hemlig", { exact: true })).toBeVisible();
    expect(writes).toEqual([]);
    await confirm.getByRole("button", { name: "Avbryt", exact: true }).click();
    await expect(confirm).toBeHidden();
    await classification.click();
    await page.getByRole("option", { name: "—", exact: true }).click();
    await expect(
      confirm.getByText("0 resurser kommer att påverkas", { exact: true })
    ).toBeVisible();
    const clear = page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" &&
        new URL(response.url()).pathname === `/api/v1${space}/`
    );
    await confirm.getByRole("button", { name: "Bekräfta", exact: true }).click();
    expect((await clear).status()).toBe(200);
    await expect(confirm).toBeHidden();
    expect(writes).toEqual([{ security_classification: null }]);
    expect(impactRequests).toHaveLength(1);
    // This is a real null request from a presented current classification,
    // not evidence that the backend previously stored that classification.
    await expect(classification).toHaveText("—");
  }
);

test(
  "members keep the real existing user disabled and find a real group before cancelling",
  { tag: "@vite" },
  async ({ page }) => {
    const space = await createSpace(page, uniqueName("Settings members"));
    const groupName = uniqueName("Avtalsgruppen");
    await apiPost(page, "/user-groups/", { name: groupName });
    await page.goto(`${space}/members`);
    await page
      .getByRole("main")
      .getByRole("button", { name: "Lägg till medlem", exact: true })
      .click();
    const member = page.getByRole("dialog", { name: "Lägg till medlem", exact: true });
    await expect(
      member.getByRole("radio", { name: E2E_CREDENTIALS.username, exact: true })
    ).toBeDisabled();
    await expect(member.getByText("Redan tillagd", { exact: true })).toBeVisible();
    await scan(page);
    await member.getByRole("button", { name: "Avbryt", exact: true }).click();
    await page
      .getByRole("main")
      .getByRole("button", { name: "Lägg till grupp", exact: true })
      .click();
    const group = page.getByRole("dialog", { name: "Lägg till grupp", exact: true });
    await group.getByRole("button", { name: "Användargrupper", exact: true }).click();
    await page.getByPlaceholder("Välj en användargrupp...", { exact: true }).fill(groupName);
    await page.getByRole("option", { name: groupName, exact: true }).click();
    await expect(group.getByRole("button", { name: new RegExp(groupName) })).toBeVisible();
    await group.getByRole("button", { name: "Avbryt", exact: true }).click();
    await expect(group).toBeHidden();
  }
);
