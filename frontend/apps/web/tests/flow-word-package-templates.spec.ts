import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { backendFetch, expectOk, MOCK_REPLY, uniqueName } from "./helpers";

const EXPORT = /^(Export|Exportera)$/;
const IMPORT = /^(Import|Importera)$/;
const WORD = new URL("../static/examples/eneo-word-template.docx", import.meta.url);
const WRONG_WORD = new URL("../static/examples/eneo-word-template-fields.docx", import.meta.url);

async function api(
  page: Page,
  request: APIRequestContext,
  path: string,
  data?: object,
  method = "POST"
) {
  const response = await backendFetch(page, request, path, {
    method: data ? method : "GET",
    ...(data ? { data } : {})
  });
  await expectOk(response, path);
  return response.json();
}

async function fixture(page: Page, request: APIRequestContext, shared: boolean) {
  const space = await api(page, request, "/api/v1/spaces/type/personal/");
  const model = space.completion_models.find((item: { name: string }) => item.name === "e2e-mock");
  const flow = await api(page, request, "/api/v1/flows/", {
    space_id: space.id,
    name: uniqueName("E2E Word package"),
    steps: [],
    metadata_json: { wizard: { transcription_enabled: false } }
  });
  const upload = await backendFetch(page, request, `/api/v1/flows/${flow.id}/template-files/`, {
    method: "POST",
    multipart: {
      upload_file: {
        name: "Rapport.docx",
        mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        buffer: await readFile(WORD)
      }
    }
  });
  await expectOk(upload, "uploading original Word template");
  const asset = await upload.json();
  const steps = [];
  for (const [index, name] of (shared
    ? ["Source", "Word report", "Second report"]
    : ["Source", "Word report"]
  ).entries()) {
    const assistant = await api(page, request, `/api/v1/flows/${flow.id}/assistants/`, { name });
    if (index === 0)
      await api(
        page,
        request,
        `/api/v1/flows/${flow.id}/assistants/${assistant.id}/`,
        {
          completion_model: { id: model.id },
          prompt: { text: "Return the provided source text." }
        },
        "PATCH"
      );
    steps.push({
      assistant_id: assistant.id,
      step_order: index + 1,
      user_description: name,
      input_source: index === 0 ? "flow_input" : "all_previous_steps",
      input_type: "text",
      ...(index > 0
        ? { input_bindings: { source_refs: [{ step_ref: "step_1", output: "text" }] } }
        : {}),
      output_mode: index === 0 ? "pass_through" : "template_fill",
      output_type: index === 0 ? "text" : "docx",
      ...(index > 0
        ? {
            output_config: {
              template_asset_id: asset.id,
              template_name: asset.name,
              template_checksum: asset.checksum,
              placeholders: ["dokument"],
              bindings: { dokument: "{{step_1.output.text}}" }
            }
          }
        : {})
    });
  }
  await api(
    page,
    request,
    `/api/v1/flows/${flow.id}/`,
    { steps, expected_revision: flow.draft_revision },
    "PATCH"
  );
  return { flow, asset, model };
}

async function exportPackage(page: Page, flowId: string, included: boolean) {
  await page.goto(`/spaces/personal/flows/${flowId}?stage=4`);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: EXPORT, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: /Export flow package|Exportera flödespaket/ });
  const checkbox = dialog.getByRole("checkbox", {
    name: /Include Word templates|Inkludera Word-mallar/
  });
  await expect(checkbox).toBeChecked();
  if (!included) {
    await checkbox.focus();
    await checkbox.press("Space");
    await expect(checkbox).not.toBeChecked();
  }
  for (const [width, height] of [
    [1024, 768],
    [1440, 1000],
    [2560, 1080]
  ]) {
    await page.setViewportSize({ width, height });
    await checkbox.scrollIntoViewIfNeeded();
    expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`word-export-${included}-${width}.png`) });
  }
  const downloadPromise = page.waitForEvent("download");
  await dialog.getByRole("button", { name: EXPORT, exact: true }).click();
  const downloaded = await downloadPromise;
  const path = test.info().outputPath(`word-${included}.eneopkg`);
  await downloaded.saveAs(path);
  return path;
}

async function openImport(page: Page, path: string, spaceRoute = "personal") {
  await page.goto(`/spaces/${spaceRoute}/flows`);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: IMPORT, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: /Import flow package|Importera flödespaket/ });
  await dialog.locator('input[type="file"]').setInputFiles(path);
  await expect(dialog.getByText("Rapport.docx", { exact: true }).first()).toBeVisible();
  return dialog;
}

async function chooseModel(page: Page) {
  await page.getByRole("button", { name: /^(Choose local resource|Välj lokal resurs)$/ }).click();
  await page.getByRole("option", { name: "E2E Mock", exact: true }).click();
}

test("included shared Word template imports to a new space once, preserves mappings and produces a document", async ({
  page,
  request
}) => {
  const { flow, asset, model } = await fixture(page, request, true);
  const file = await exportPackage(page, flow.id, true);
  const space = await api(page, request, "/api/v1/spaces/", {
    name: uniqueName("E2E Word destination")
  });
  await api(
    page,
    request,
    `/api/v1/spaces/${space.id}/`,
    { completion_models: [{ id: model.id }] },
    "PATCH"
  );
  const dialog = await openImport(page, file, space.id);
  await expect(dialog).toContainText(/Included in the package|Ingår i paketet/);
  await chooseModel(page);
  const importResponse = page.waitForResponse((response) =>
    response.url().endsWith("/flow-packages/imports/")
  );
  await dialog.getByRole("button", { name: /Import as draft|Importera som utkast/ }).click();
  const response = await importResponse;
  expect(response.ok(), await response.text()).toBe(true);
  const receipt = await response.json();
  await page.waitForURL(new RegExp(`/flows/${receipt.flow_id}`));
  const imported = await api(page, request, `/api/v1/flows/${receipt.flow_id}/`);
  const localId = imported.steps[1].output_config.template_asset_id;
  expect(localId).not.toBe(asset.id);
  expect(imported.steps[2].output_config.template_asset_id).toBe(localId);
  expect(imported.steps[1].output_config.bindings).toEqual({
    dokument: "{{ step_1.output.text }}"
  });
  const assets = await api(page, request, `/api/v1/flows/${receipt.flow_id}/template-files/`);
  expect(assets.items ?? assets).toHaveLength(1);
  await api(page, request, `/api/v1/flows/${receipt.flow_id}/publish/`, {});
  await page.reload();
  await page.getByRole("button", { name: /^(Run flow|Kör flöde)$/ }).click();
  const run = page.getByRole("dialog", { name: /^(Run flow|Kör flöde)$/ });
  await run.getByRole("button", { name: /^(Next|Nästa)$/ }).click();
  await run
    .getByRole("textbox", { name: /^(Input|Indata|Material|Underlag)$/ })
    .fill("Source material for the imported Word template.");
  await run.getByRole("button", { name: /^(Next|Nästa)$/ }).click();
  await run.getByRole("button", { name: /^(Start run|Starta körning)$/ }).click();
  await page
    .locator("#panel-history")
    .getByRole("button", { name: /^(View details|Visa detaljer)$/ })
    .click();
  const download = page.getByRole("button", { name: /^(Download|Ladda ner) .*\.docx$/ }).last();
  await expect(download).toBeVisible({ timeout: 60000 });
  const downloaded = page.waitForEvent("download");
  await download.click();
  await (await downloaded).saveAs(test.info().outputPath("imported-filled-word.docx"));
  const runs = await api(page, request, `/api/v1/flows/${receipt.flow_id}/runs/`);
  const results = await api(
    page,
    request,
    `/api/v1/flows/${receipt.flow_id}/runs/${(runs.items ?? runs)[0].id}/steps/`
  );
  expect(JSON.stringify(results)).toContain(MOCK_REPLY);
  await page.screenshot({
    path: test.info().outputPath("imported-word-result.png"),
    fullPage: true
  });
});

test("omitted Word template requires matching fields and recovers without losing model selection", async ({
  page,
  request
}) => {
  const { flow } = await fixture(page, request, false);
  const file = await exportPackage(page, flow.id, false);
  const dialog = await openImport(page, file);
  const submit = dialog.getByRole("button", { name: /Import as draft|Importera som utkast/ });
  await chooseModel(page);
  await expect(submit).toBeDisabled();
  const upload = dialog.getByLabel(/Word file for|Word-fil till/);
  await upload.setInputFiles({
    name: "wrong.docx",
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: await readFile(WRONG_WORD)
  });
  await expect(
    dialog.getByRole("alert").filter({ hasText: /Missing tags|Saknade taggar/ })
  ).toContainText("dokument");
  await expect(submit).toBeDisabled();
  await page.screenshot({ path: test.info().outputPath("word-import-mismatch.png") });
  await upload.setInputFiles({
    name: "replacement.docx",
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: await readFile(WORD)
  });
  await expect(dialog.getByText("replacement.docx", { exact: true })).toBeVisible();
  await expect(submit).toBeEnabled();
  for (const width of [1024, 1440, 2560]) {
    await page.setViewportSize({ width, height: 900 });
    await page.screenshot({ path: test.info().outputPath(`word-import-${width}.png`) });
    const overflow = await dialog.evaluate((el) => ({
      width: el.clientWidth,
      scroll: el.scrollWidth,
      children: Array.from(el.querySelectorAll("*"))
        .filter(
          (child) => child.getBoundingClientRect().right > el.getBoundingClientRect().right + 1
        )
        .map((child) => ({
          tag: child.tagName,
          classes: child.className,
          text: child.textContent?.slice(0, 80)
        }))
        .slice(0, 12)
    }));
    expect(overflow.scroll, JSON.stringify(overflow)).toBeLessThanOrEqual(overflow.width + 1);
  }
  const responsePromise = page.waitForResponse((response) =>
    response.url().endsWith("/flow-packages/imports/")
  );
  await submit.click();
  const response = await responsePromise;
  expect(response.ok(), await response.text()).toBe(true);
  const imported = await response.json();
  await page.waitForURL(new RegExp(`/flows/${imported.flow_id}`));
  const draft = await api(page, request, `/api/v1/flows/${imported.flow_id}/`);
  expect(draft.steps[1].output_config.template_name).toBe("replacement.docx");
  expect(draft.steps[1].output_config.bindings).toEqual({ dokument: "{{ step_1.output.text }}" });
});
