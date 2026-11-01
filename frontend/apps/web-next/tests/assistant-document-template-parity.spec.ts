import AxeBuilder from "@axe-core/playwright";
import type { Schema } from "../src/lib/api/models";
import { WCAG_22_AA_TAGS } from "../src/test/wcag";
import { expect, test } from "./csp";
import { apiPost, createSpace, uniqueName } from "./helpers";

// Template bytes come from the configured document runtime; no generated output is requested.
test(
  "persists the assistant's three document-template modes through the actual backend",
  { tag: "@vite" },
  async ({ page }) => {
    test.setTimeout(90_000);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.goto("/admin/tools?tab=functions");
    const fileCreation = page.getByRole("region", { name: "Skapa fil", exact: true });
    const turnOn = fileCreation.getByRole("button", { name: "Slå på", exact: true });
    const library = fileCreation.getByRole("region", { name: "Dokumentmallar", exact: true });
    await expect(fileCreation).toBeVisible();
    await expect(turnOn.or(library)).toBeVisible();
    if (await turnOn.isVisible()) await turnOn.click();
    await expect(library).toBeVisible();
    const builtin = await page.request.get("/api/v1/document-templates/builtin/?language=sv");
    expect(builtin.status()).toBe(200);
    const bytes = await builtin.body();
    expect(bytes.subarray(0, 2).toString()).toBe("PK");
    const templates: Schema<"DocumentTemplatePublic">[] = [];
    for (const isDefault of [true, false]) {
      await library.getByRole("button", { name: "Ladda upp mall" }).click();
      const upload = page.getByRole("dialog", { name: "Ladda upp mall" });
      await upload.locator('input[type="file"]').setInputFiles({
        name: "assistant-template.docx",
        mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        buffer: bytes
      });
      await upload
        .getByRole("textbox", { name: "Namn", exact: true })
        .fill(uniqueName(isDefault ? "Standardmall" : "Alternativ mall"));
      await upload
        .getByRole("checkbox", { name: "Gör till organisationens standard" })
        .setChecked(isDefault);
      const uploaded = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/v1/document-templates/" &&
          response.request().method() === "POST"
      );
      await upload.getByRole("button", { name: "Spara mall" }).click();
      const response = await uploaded;
      expect(response.status()).toBe(201);
      templates.push(await response.json());
      await expect(upload).toBeHidden();
    }
    const [standard, alternative] = templates;
    expect(standard).toBeDefined();
    expect(alternative).toBeDefined();
    if (!standard || !alternative) throw new Error("Both real templates must exist");
    const space = await createSpace(page, uniqueName("Mallval"));
    const enabled = await page.evaluate(async (space) => {
      const session = await fetch("/api/v1/auth/session/");
      const generation = session.headers.get("Eneo-Session-Generation");
      if (session.status !== 204 || !generation) throw new Error("Fixture session probe failed");
      const response = await fetch(`/api/v1${space}/`, {
        method: "PATCH",
        headers: { "content-type": "application/json", "Eneo-Session-Generation": generation },
        body: JSON.stringify({ enabled_capabilities: ["file_creation"] })
      });
      return response.status;
    }, space);
    expect(enabled).toBe(200);
    const assistant = await apiPost(page, `${space}/applications/assistants/`, {
      name: uniqueName("Dokumentassistent")
    });
    await apiPost(page, `/assistants/${assistant}/`, {
      enabled_capabilities: ["file_creation"],
      document_template: { mode: "builtin", template_id: null }
    });
    const path = `/api/v1/assistants/${assistant}/`;
    const editor = `${space}/assistants/${assistant}/edit?section=capabilities`;
    const requests: string[] = [];
    page.on("request", (request) => {
      const pathname = new URL(request.url()).pathname;
      if (pathname.startsWith("/api/v1/document-templates/")) requests.push(pathname);
    });
    const available = page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api/v1/document-templates/available/"
    );
    await page.goto(editor);
    const optionsResponse = await available;
    expect(optionsResponse.status()).toBe(200);
    const options: Schema<"DocumentTemplateOptions"> = await optionsResponse.json();
    expect(options.items).toEqual(
      expect.arrayContaining([
        { id: standard.id, name: standard.name, is_default: true },
        { id: alternative.id, name: alternative.name, is_default: false }
      ])
    );
    const picker = page.locator("#assistant-document-template");
    await expect(
      picker.getByText("Dokumentmall: Eneos inbyggda mall", { exact: true })
    ).toBeVisible();
    await picker.getByRole("button", { name: "Ändra dokumentmall" }).click();
    async function saveMode(name: string, choice: Schema<"DocumentTemplateChoicePublic">) {
      const written = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === path && response.request().method() === "POST"
      );
      await picker.getByRole("radio", { name, exact: true }).click();
      const response = await written;
      expect(response.status()).toBe(200);
      expect(response.request().postDataJSON().document_template).toEqual(choice);
      expect((await response.json()).document_template).toEqual(choice);
      const persisted = await page.request.get(path);
      expect(persisted.status()).toBe(200);
      expect((await persisted.json()).document_template).toEqual(choice);
    }
    await saveMode("Organisationens standard", { mode: "default", template_id: null });
    await expect(
      picker.getByText(`Dokumentmall: ${standard.name} (organisationens standard)`, { exact: true })
    ).toBeVisible();
    await saveMode("En annan mall", { mode: "selected", template_id: standard.id });
    await picker.getByRole("combobox", { name: "En annan mall" }).click();
    const selected = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === path && response.request().method() === "POST"
    );
    await page.getByRole("option", { name: alternative.name, exact: true }).click();
    expect((await selected).status()).toBe(200);
    await page.reload();
    await expect(
      picker.getByText(`Dokumentmall: ${alternative.name}`, { exact: true })
    ).toBeVisible();
    const persisted = await page.request.get(path);
    expect((await persisted.json()).document_template).toEqual({
      mode: "selected",
      template_id: alternative.id
    });
    await picker.getByRole("button", { name: "Ändra dokumentmall" }).click();
    const scan = await new AxeBuilder({ page })
      .include("#assistant-document-template")
      .withTags(WCAG_22_AA_TAGS)
      .analyze();
    expect(scan.violations).toEqual([]);
    await picker.screenshot({
      path: test.info().outputPath("assistant-document-template-desktop.png"),
      animations: "disabled"
    });
    await saveMode("Eneos inbyggda mall", { mode: "builtin", template_id: null });
    await page.reload();
    await expect(
      picker.getByText("Dokumentmall: Eneos inbyggda mall", { exact: true })
    ).toBeVisible();
    // The read failure is injected; keyboard recovery continues to the actual endpoint.
    let failedOptions = false;
    let releaseOptions!: () => void;
    const heldOptions = new Promise<void>((resolve) => {
      releaseOptions = resolve;
    });
    await page.route("**/api/v1/document-templates/available/", async (route) => {
      if (!failedOptions) {
        failedOptions = true;
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ message: "Template options unavailable" })
        });
      } else {
        await heldOptions;
        await route.continue();
      }
    });
    let unexpectedWrites = 0;
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === path && request.method() === "POST")
        unexpectedWrites += 1;
    });
    await page.reload();
    const readRetry = picker.getByRole("button", { name: "Försök igen", exact: true });
    await expect(readRetry).toBeVisible();
    await readRetry.focus();
    await page.keyboard.press("Enter");
    try {
      await expect(readRetry).toHaveAttribute("aria-busy", "true");
      await expect(readRetry).toBeFocused();
    } finally {
      releaseOptions();
    }
    await expect(readRetry).toBeHidden();
    await expect(
      picker.getByText("Dokumentmall: Eneos inbyggda mall", { exact: true })
    ).toBeFocused();
    expect(unexpectedWrites).toBe(0);
    expect(requests.length).toBeGreaterThan(0);
    expect(new Set(requests)).toEqual(new Set(["/api/v1/document-templates/available/"]));
    expect(pageErrors).toEqual([]);
  }
);
