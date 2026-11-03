import AxeBuilder from "@axe-core/playwright";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { uniqueName } from "./helpers";
import { WCAG_22_AA_TAGS } from "../src/test/wcag";

// Real cookie authentication, tool-runtime DOCX bytes and template persistence.
// Rendering/validation failures and retry races belong to the component tests.
test(
  "administers Word templates through the actual backend",
  { tag: "@vite" },
  async ({ page }) => {
    test.setTimeout(90_000);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.goto("/admin/tools?tab=functions");
    const fileCreation = page.getByRole("region", { name: "Skapa fil", exact: true });
    await expect(fileCreation).toBeVisible();
    const turnOn = fileCreation.getByRole("button", { name: "Slå på", exact: true });
    if (await turnOn.count()) await turnOn.click();
    const library = fileCreation.getByRole("region", { name: "Dokumentmallar", exact: true });
    await expect(library).toBeVisible();

    const builtinDownload = page.waitForEvent("download");
    await library.getByRole("button", { name: "Ladda ner inbyggd mall" }).click();
    const builtin = await builtinDownload;
    expect(builtin.suggestedFilename()).toBe("eneo-template-sv.docx");
    const builtinPath = await builtin.path();
    expect(builtinPath).not.toBeNull();
    const original = await readFile(builtinPath!);
    expect(original.subarray(0, 2).toString()).toBe("PK");
    const replacementResponse = await page.request.get(
      "/api/v1/document-templates/builtin/?language=en"
    );
    expect(replacementResponse.status()).toBe(200);
    const replacement = await replacementResponse.body();
    expect(replacement.equals(original)).toBe(false);

    const name = uniqueName("Kommunmall");
    await library.getByRole("button", { name: "Ladda upp mall" }).click();
    const upload = page.getByRole("dialog", { name: "Ladda upp mall" });
    await upload.locator('input[type="file"]').setInputFiles({
      name: "kommunmall.docx",
      mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      buffer: original
    });
    await upload.getByRole("textbox", { name: "Namn", exact: true }).fill(name);
    await upload.getByRole("checkbox", { name: "Gör till organisationens standard" }).uncheck();
    const uploadedResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/v1/document-templates/" &&
        response.request().method() === "POST"
    );
    await upload.getByRole("button", { name: "Spara mall" }).click();
    const response = await uploadedResponse;
    expect(response.status()).toBe(201);
    const saved: Schema<"DocumentTemplatePublic"> = await response.json();
    expect(saved).toMatchObject({
      name,
      filename: "kommunmall.docx",
      is_default: false,
      status: "ready",
      sha256: createHash("sha256").update(original).digest("hex")
    });
    await expect(upload).toBeHidden();
    const row = library
      .getByRole("listitem")
      .filter({ has: page.getByText(name, { exact: true }) });
    await row.getByRole("button", { name: "Visa kontroll" }).click();
    await expect(row.getByRole("heading", { name: "Kontroll av mallen" })).toBeVisible();
    await expect(row.getByRole("heading", { name: "Fält i mallen" })).toBeVisible();
    const desktopScan = await new AxeBuilder({ page })
      .include('section[aria-labelledby="capability-file_creation"]')
      .withTags(WCAG_22_AA_TAGS)
      .analyze();
    expect(desktopScan.violations).toEqual([]);
    await library.screenshot({ path: test.info().outputPath("document-templates-desktop.png") });

    await row.getByRole("button", { name: `Åtgärder: ${name}` }).click();
    await page.getByRole("menuitem", { name: "Byt namn", exact: true }).click();
    const rename = page.getByRole("dialog", { name: "Byt namn", exact: true });
    const renamed = `${name} reviderad`;
    await rename.getByRole("textbox", { name: "Namn", exact: true }).fill(renamed);
    await rename.getByRole("button", { name: "Spara mall" }).click();
    await expect(rename).toBeHidden();
    const renamedRow = library
      .getByRole("listitem")
      .filter({ has: page.getByText(renamed, { exact: true }) });
    await renamedRow.getByRole("button", { name: `Åtgärder: ${renamed}` }).click();
    await page.getByRole("menuitem", { name: "Använd som standard", exact: true }).click();
    await expect(renamedRow.getByText("Standard", { exact: true })).toBeVisible();

    await renamedRow.getByRole("button", { name: `Åtgärder: ${renamed}` }).click();
    await page.getByRole("menuitem", { name: "Byt fil", exact: true }).click();
    const replace = page.getByRole("dialog", { name: "Byt fil", exact: true });
    await replace.locator('input[type="file"]').setInputFiles({
      name: "replacement.docx",
      mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      buffer: replacement
    });
    await expect(replace).toHaveCSS("opacity", "1");
    const dialogScan = await new AxeBuilder({ page }).withTags(WCAG_22_AA_TAGS).analyze();
    expect(dialogScan.violations).toEqual([]);
    await page.screenshot({
      path: test.info().outputPath("document-template-replace-desktop.png")
    });
    const replacedResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/v1/document-templates/${saved.id}/content/` &&
        response.request().method() === "PUT"
    );
    await replace.getByRole("button", { name: "Spara mall" }).click();
    expect((await replacedResponse).status()).toBe(200);
    await expect(replace).toBeHidden();
    const currentResponse = await page.request.get(`/api/v1/document-templates/${saved.id}/`);
    expect(currentResponse.status()).toBe(200);
    const current: Schema<"DocumentTemplatePublic"> = await currentResponse.json();
    expect(current).toMatchObject({
      id: saved.id,
      name: renamed,
      filename: "replacement.docx",
      is_default: true,
      sha256: createHash("sha256").update(replacement).digest("hex")
    });

    await renamedRow.getByRole("button", { name: `Åtgärder: ${renamed}` }).click();
    const storedDownload = page.waitForEvent("download");
    await page.getByRole("menuitem", { name: "Ladda ner", exact: true }).click();
    const stored = await storedDownload;
    expect(stored.suggestedFilename()).toBe("replacement.docx");
    const storedPath = await stored.path();
    expect(await readFile(storedPath!)).toEqual(replacement);
    await renamedRow.getByRole("button", { name: `Åtgärder: ${renamed}` }).click();
    await page.getByRole("menuitem", { name: "Ta bort mall", exact: true }).click();
    const confirmation = page.getByRole("alertdialog");
    await expect(confirmation.getByText(renamed, { exact: true })).toBeVisible();
    await confirmation.getByRole("button", { name: "Ta bort mall", exact: true }).click();
    await expect(confirmation).toBeHidden();
    await expect(renamedRow).toHaveCount(0);
    await expect(
      library.getByRole("heading", { name: "Dokumentmallar", exact: true })
    ).toBeFocused();
    expect((await page.request.get(`/api/v1/document-templates/${saved.id}/`)).status()).toBe(404);
    expect(pageErrors).toEqual([]);
  }
);
