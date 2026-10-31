import { expect, test } from "./csp";
import { apiPost, apiPostJson, createSpace, sessionResponseHeaders, uniqueName } from "./helpers";
import type { components } from "../src/lib/api/schema";
type Assistant = components["schemas"]["AssistantPublic"];

test.use({ viewport: { width: 320, height: 800 }, isMobile: true, hasTouch: true });
test("edits, restores and deletes real prompt history and validates, previews and downloads a native avatar", async ({
  page
}, info) => {
  test.setTimeout(90_000);
  const space = await createSpace(page, uniqueName("Editor parity"));
  const assistant = await apiPostJson<Assistant>(page, `${space}/applications/assistants/`, {
    name: uniqueName("Parity assistant")
  });
  const path = `/assistants/${assistant.id}/`;
  await apiPost(page, path, {
    prompt: { text: "First native instructions", description: "First native marker" }
  });
  await apiPost(page, path, {
    prompt: { text: "Current native instructions", description: "Current native marker" }
  });
  const editor = `${space}/assistants/${assistant.id}/edit`;
  await page.goto(`${editor}?section=instructions`);
  await page.getByRole("button", { name: "Visa prompthistorik" }).click();
  let dialog = page.getByRole("dialog", { name: "Prompthistorik" });
  await expect(dialog.getByText("Current native instructions", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Återställ denna version" })).toBeDisabled();
  await dialog.getByRole("button", { name: /First native marker/ }).click();
  await dialog.getByRole("button", { name: "Redigera beskrivning" }).click();
  await dialog.getByRole("textbox", { name: "Beskrivning" }).fill("Edited native marker");
  await page.keyboard.press("Escape");
  const leave = page.getByRole("alertdialog", { name: "Lämna sidan?" });
  await expect(leave).toBeVisible();
  await leave.getByRole("button", { name: "Avbryt", exact: true }).click();
  await expect(dialog.getByRole("textbox", { name: "Beskrivning" })).toHaveValue(
    "Edited native marker"
  );
  let release!: () => void;
  let sawWrite!: () => void;
  const held = new Promise<void>((done) => {
    release = done;
  });
  const writing = new Promise<void>((done) => {
    sawWrite = done;
  });
  // Delay one real PATCH to verify pending close handling; the backend still saves it.
  await page.route("**/api/v1/prompts/**", async (route) => {
    if (route.request().method() === "PATCH") {
      sawWrite();
      await held;
    }
    await route.continue();
  });
  const edited = page.waitForResponse(
    (r) => r.url().includes("/api/v1/prompts/") && r.request().method() === "PATCH"
  );
  await dialog.getByRole("button", { name: "Spara ändringar" }).click();
  await writing;
  try {
    await page.keyboard.press("Escape");
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    await expect(dialog).toBeVisible();
  } finally {
    release();
  }
  expect((await edited).ok()).toBe(true);
  await page.unroute("**/api/v1/prompts/**");
  await expect(dialog.locator("p").filter({ hasText: "Edited native marker" })).toBeVisible();
  await dialog.getByRole("button", { name: "Stäng", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "Visa prompthistorik" }).click();
  dialog = page.getByRole("dialog", { name: "Prompthistorik" });
  await dialog.getByRole("button", { name: /Edited native marker/ }).click();
  const restored = page.waitForResponse(
    (r) =>
      r.url().includes(path) &&
      r.request().method() === "POST" &&
      r.request().postDataJSON().prompt?.text === "First native instructions"
  );
  await dialog.getByRole("button", { name: "Återställ denna version" }).click();
  const saved: Assistant = await (await restored).json();
  expect(saved.prompt?.description).toMatch(/^Återställd prompt från /);
  await expect(page.locator("#assistant-prompt")).toHaveValue("First native instructions");
  await page.getByRole("button", { name: "Visa prompthistorik" }).click();
  dialog = page.getByRole("dialog", { name: "Prompthistorik" });
  await dialog.getByRole("button", { name: /Edited native marker/ }).click();
  await dialog.getByRole("button", { name: "Radera prompt" }).click();
  await expect(dialog.getByText("Vill du verkligen radera denna version?")).toBeVisible();
  const removed = page.waitForResponse(
    (r) => r.url().includes("/api/v1/prompts/") && r.request().method() === "DELETE"
  );
  await dialog.getByRole("button", { name: "Ta bort", exact: true }).click();
  expect((await removed).ok()).toBe(true);
  await expect(dialog.getByRole("button", { name: /Edited native marker/ })).toHaveCount(0);
  await dialog.screenshot({ path: info.outputPath("phone-history.png") });
  await dialog.getByRole("button", { name: "Stäng", exact: true }).click();
  await page.goto(`${editor}?section=general`);
  const avatar = page.locator('[data-editor-section="general"] input[type="file"]');
  const uploads: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/api/v1/icons/") && request.method() === "POST")
      uploads.push(request.url());
  });
  await avatar.setInputFiles({
    name: "wrong.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("not an image")
  });
  await expect(page.getByText(/Endast PNG, JPEG och WebP/)).toBeVisible();
  expect(uploads).toHaveLength(0);
  const avatarSaved = page.waitForResponse(
    (r) =>
      r.url().includes(path) &&
      r.request().method() === "POST" &&
      typeof r.request().postDataJSON().icon_id === "string"
  );
  await avatar.setInputFiles({
    name: "avatar.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=",
      "base64"
    )
  });
  expect((await avatarSaved).ok()).toBe(true);
  expect(uploads).toHaveLength(1);
  await page.getByRole("button", { name: "Visa avatar" }).click();
  const preview = page.getByRole("dialog");
  await expect(preview.getByRole("img")).toBeVisible();
  const download = page.waitForEvent("download");
  await preview.getByRole("button", { name: "Ladda ner", exact: true }).click();
  expect((await download).url()).toContain("/api/v1/icons/");
  await preview.screenshot({ path: info.outputPath("phone-avatar.png") });
  await preview.getByRole("button", { name: "Stäng", exact: true }).click();
  await page.goto(`${editor}?section=mcp`);
  await expect(page.getByText("Inga MCP-servrar tillgängliga ännu.")).toBeVisible();
  await expect(page.getByRole("link", { name: /Aktivera MCP-servrar/ })).toHaveAttribute(
    "href",
    `${space}/settings?section=tools`
  );
});

test("explains model-specific settings and governed startup defaults", async ({ page }, info) => {
  const space = await createSpace(page, uniqueName("Editor explanations"));
  const assistant = await apiPostJson<Assistant>(page, `${space}/applications/assistants/`, {
    name: uniqueName("Explanations")
  });
  const original = (await (
    await page.request.get(`/api/v1${space}/`)
  ).json()) as components["schemas"]["SpacePublic"];
  // Capability/policy fixtures isolate explanations; prompt and icon writes above are real.
  await page.route(`**/api/v1${space}/`, (route) =>
    route.fulfill({
      headers: sessionResponseHeaders(route),
      json: {
        ...original,
        completion_models: original.completion_models.map((model) => ({
          ...model,
          supported_model_kwargs: { temperature: { supported: false }, top_p: { supported: true } }
        }))
      }
    })
  );
  await page.route(`**/api/v1/assistants/${assistant.id}/`, (route) =>
    route.fulfill({
      headers: sessionResponseHeaders(route),
      json: {
        ...assistant,
        effective_config: {
          models_enforced: false,
          available_models: [],
          mcp_enforced: true,
          prompt_locked: false,
          available_mcp_servers: [
            { id: "provider", name: "Provider secret name", purpose: "web_search" }
          ],
          enabled_capabilities: ["web_search"],
          default_disabled_capabilities: ["web_search"],
          available_capabilities: [{ purpose: "web_search", available: true }]
        }
      }
    })
  );
  const editor = `${space}/assistants/${assistant.id}/edit`;
  await page.goto(`${editor}?section=ai`);
  await expect(page.getByRole("combobox", { name: "Modellbeteende" })).toBeDisabled();
  await expect(page.getByText(/modellspecifika parametrar/i)).toBeVisible();
  await expect(page.getByLabel("Top P")).toHaveAttribute("aria-describedby", /help/);
  await page.goto(`${editor}?section=mcp`);
  await expect(page.getByText("Webbsökning", { exact: true })).toBeVisible();
  await expect(page.getByText("Provider secret name")).toHaveCount(0);
  await page.goto(`${editor}?section=capabilities`);
  await expect(page.getByText("Av från början i chatten")).toBeVisible();
  await expect(page.getByRole("switch", { name: "Webbsökning" })).toBeDisabled();
  await expect(page.getByRole("switch", { name: "Webbsökning" })).not.toBeChecked();
  await page.screenshot({ path: info.outputPath("phone-governance.png"), fullPage: true });
});
