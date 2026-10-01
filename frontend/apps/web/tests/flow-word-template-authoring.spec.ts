import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { backendFetch, expectOk, MOCK_REPLY, uniqueName } from "./helpers";

const UPLOAD = /^(Upload template|Ladda upp mall)$/;
const SOURCE = /^(Text for|Text till) Dokument$/;
const RETRY = /^(Try again|Försök igen)$/;
const EMPTY = /^(Leave empty|Lämna tomt)$/;
const EXAMPLE = /^(Download example template|Ladda ner exempelmall)$/;
const TEMPLATE = "Template step";
const TEXT_STEP = "Source text";
const FILE = new URL("../static/examples/eneo-word-template.docx", import.meta.url);
const FIELDS_FILE = new URL("../static/examples/eneo-word-template-fields.docx", import.meta.url);

async function api(page: Page, request: APIRequestContext, path: string, data?: object) {
  const response = await backendFetch(page, request, path, {
    method: data ? "POST" : "GET",
    ...(data ? { data } : {})
  });
  await expectOk(response, path);
  return response.json();
}

async function createFlow(page: Page, request: APIRequestContext, includeForm = false) {
  const space = await api(page, request, "/api/v1/spaces/type/personal/");
  const flow = await api(page, request, "/api/v1/flows/", {
    space_id: space.id,
    name: uniqueName("E2E Word mapping"),
    steps: [],
    metadata_json: {
      wizard: { transcription_enabled: false },
      ...(includeForm
        ? { form_schema: { fields: [{ name: "brukarens_namn", type: "text", required: false }] } }
        : {})
    }
  });
  const steps = [];
  for (const [index, name] of [TEXT_STEP, "Other step", TEMPLATE].entries()) {
    const assistant = await api(page, request, `/api/v1/flows/${flow.id}/assistants/`, { name });
    steps.push({
      assistant_id: assistant.id,
      step_order: index + 1,
      user_description: name,
      input_source: index === 0 ? "flow_input" : "previous_step",
      input_type: "text",
      output_type: index === 2 ? "docx" : "text",
      output_mode: index === 2 ? "template_fill" : "pass_through",
      ...(index === 2 ? { output_config: { bindings: {}, placeholders: [] } } : {})
    });
  }
  const response = await backendFetch(page, request, `/api/v1/flows/${flow.id}/`, {
    method: "PATCH",
    data: { steps, expected_revision: flow.draft_revision }
  });
  await expectOk(response, "creating Word template flow");
  return response.json();
}

async function selectStep(page: Page, name: string) {
  await page.getByRole("listitem").filter({ hasText: name }).getByRole("button").first().click();
}

async function openTemplate(page: Page, flowId: string) {
  await page.goto(`/spaces/personal/flows/${flowId}?stage=4`);
  await page.waitForLoadState("networkidle");
  await selectStep(page, TEMPLATE);
  if (!(await page.getByRole("button", { name: UPLOAD }).isVisible())) {
    await page.getByRole("button", { name: /^(Result|Resultat)\b/ }).click();
  }
  await expect(page.getByRole("button", { name: UPLOAD })).toBeVisible();
}

async function upload(page: Page, fileName = "existing-template.docx") {
  await page.locator('input[type="file"][accept=".docx"]').setInputFiles({
    name: fileName,
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: await readFile(FILE)
  });
}

async function mapText(page: Page) {
  await page.getByRole("button", { name: SOURCE }).click();
  await page.getByRole("option", { name: /Source text/, exact: false }).click();
}

async function savedTemplate(page: Page, request: APIRequestContext, flowId: string) {
  const flow = await api(page, request, `/api/v1/flows/${flowId}/`);
  return flow.steps[2].output_config;
}

test("multi-field example shows real locations and keyboard navigation preserves mappings", async ({
  page,
  request
}) => {
  const flow = await createFlow(page, request, true);
  await openTemplate(page, flow.id);
  const downloadPromise = page.waitForEvent("download");
  await page
    .getByRole("link", { name: /^(Example with several fields|Exempel med flera fält)$/ })
    .click();
  const example = await downloadPromise;
  expect(example.suggestedFilename()).toBe("eneo-word-template-fields.docx");
  const filePath = test.info().outputPath("eneo-word-template-fields.docx");
  await example.saveAs(filePath);
  expect(await readFile(filePath)).toEqual(await readFile(FIELDS_FILE));
  await page.locator('input[type="file"][accept=".docx"]').setInputFiles(filePath);
  const overview = page.getByRole("button", {
    name: /^(Show places in the template|Visa platser i mallen)$/
  });
  await expect(overview).toBeVisible();
  await overview.focus();
  await overview.press("Enter");
  const locations = page
    .getByRole("list")
    .filter({ has: page.getByRole("button", { name: /^(Go to field|Gå till fältet) Namn$/ }) });
  const names = await locations.getByRole("button").allTextContents();
  expect(names).toHaveLength(4);
  for (const [index, label] of ["Namn", "Bakgrund", "Bedömning", "Nästa steg"].entries()) {
    expect(names[index]).toContain(label);
  }
  await expect(locations).toContainText(/In the document body|I dokumentets huvudtext/);
  await expect(locations).toContainText(/Under the heading “Bedömning”|Under rubriken ”Bedömning”/);
  const target = page.getByRole("button", { name: /^(Go to field|Gå till fältet) Bedömning$/ });
  await target.focus();
  await target.press("Enter");
  const source = page.getByRole("button", { name: /^(Text for|Text till) Bedömning$/ });
  await expect(source).toBeFocused();
  await source.press("Enter");
  await page.getByRole("option", { name: /Source text/ }).click();
  await expect
    .poll(async () => (await savedTemplate(page, request, flow.id))?.bindings?.bedomning)
    .toBe("{{step_1.output.text}}");
  const nameSource = page.getByRole("button", { name: /^(Text for|Text till) Namn$/ });
  await nameSource.click();
  await page.getByRole("option", { name: /^(Field|Fält): brukarens_namn$/ }).click();
  const nextSource = page.getByRole("button", { name: /^(Text for|Text till) Nästa steg$/ });
  await nextSource.click();
  await page.getByRole("option", { name: EMPTY }).click();
  for (const [width, height] of [
    [1024, 768],
    [1440, 1000],
    [2560, 1080]
  ]) {
    await page.setViewportSize({ width, height });
    await overview.scrollIntoViewIfNeeded();
    expect(
      await locations.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)
    ).toBe(true);
    await page.screenshot({
      path: test.info().outputPath(`word-locations-${width}.png`),
      fullPage: true
    });
  }
  await page.getByRole("button", { name: /^(Refresh|Uppdatera)$/ }).click();
  await expect(source).toContainText(TEXT_STEP);
  await expect(nameSource).toContainText("brukarens_namn");
  await expect(nextSource).toContainText(/Leave empty|Lämna tomt/);
  await expect
    .poll(async () => (await savedTemplate(page, request, flow.id)).bindings)
    .toMatchObject({
      namn: "{{flow_input.brukarens_namn}}",
      bedomning: "{{step_1.output.text}}",
      nasta_steg: ""
    });
});

test("invalid Word files show actionable errors and a replacement upload recovers", async ({
  page,
  request
}) => {
  const flow = await createFlow(page, request);
  await openTemplate(page, flow.id);
  await page.locator('input[type="file"][accept=".docx"]').setInputFiles({
    name: "invalid.docx",
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: Buffer.from("This is not a Word archive")
  });
  const error = page
    .getByRole("alert")
    .filter({ hasText: /Template needs attention|Mallen behöver åtgärdas/ });
  await expect(error).toBeVisible();
  await expect(error).toContainText(/DOCX|Word/i);
  await error.scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath("word-upload-error.png"), fullPage: true });
  await expect(page.getByRole("button", { name: RETRY })).toHaveCount(0);
  await expect(page.locator('[data-sonner-toast][data-type="success"]')).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /How to prepare your template|Så förbereder du mallen/ })
  ).toBeVisible();
  await upload(page);
  await expect(error).toHaveCount(0);
  await mapText(page);
  await expect
    .poll(async () => (await savedTemplate(page, request, flow.id))?.bindings?.dokument)
    .toBe("{{step_1.output.text}}");
});

test("simple mode exposes Word guidance, a valid example and editable field mappings", async ({
  page,
  request
}) => {
  const flow = await createFlow(page, request);
  await openTemplate(page, flow.id);
  await expect(page.getByRole("button", { name: /^(Show expression|Visa uttryck)$/ })).toHaveCount(
    0
  );
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: EXAMPLE }).click();
  const example = await downloadPromise;
  expect(example.suggestedFilename()).toBe("eneo-word-template.docx");
  expect(await example.failure()).toBeNull();
  await page
    .getByRole("button", { name: /^(How to prepare your template|Så förbereder du mallen)$/ })
    .click();
  await expect(page.getByText(/unique tag|unik tagg/)).toBeVisible();
  await expect(page.getByText(/Word for Mac can use|Word för Mac kan använda/)).toBeVisible();
  await expect(
    page.locator(
      'a[href="https://support.microsoft.com/en-gb/word/show-the-developer-tab-in-word"]'
    )
  ).toBeVisible();
  await expect(
    page.locator(
      'a[href="https://support.microsoft.com/en-us/word/create-a-form-in-word-that-users-can-complete-or-print"]'
    )
  ).toBeVisible();
  await page.getByText(/unique tag|unik tagg/).scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath("word-setup-guide.png"), fullPage: true });
  const downloadedPath = test.info().outputPath("eneo-word-template(1).docx");
  await example.saveAs(downloadedPath);
  expect(
    createHash("sha256")
      .update(await readFile(downloadedPath))
      .digest("hex")
  ).toBe(
    createHash("sha256")
      .update(await readFile(FILE))
      .digest("hex")
  );
  await page.locator('input[type="file"][accept=".docx"]').setInputFiles(downloadedPath);
  await expect(page.getByRole("button", { name: SOURCE })).toBeVisible();
  await expect(page.getByText(/^(Template checked|Mallen är kontrollerad)$/)).toBeVisible();
  const exampleText = page.getByRole("button", {
    name: /^(Show text to replace|Visa texten som ersätts)$/
  });
  await expect(exampleText).toHaveAttribute("aria-expanded", "false");
  await exampleText.click();
  await expect(exampleText).toHaveAttribute("aria-expanded", "true");
  const preview = page.getByRole("region", {
    name: /This text is replaced|Den här texten ersätts/
  });
  await expect(preview).toBeVisible();
  await expect(preview).toContainText("Exempelmall för Eneo\n\nDen här mallen");
  await preview.focus();
  await expect(preview).toBeFocused();
  await page.screenshot({
    path: test.info().outputPath("word-readable-preview.png"),
    fullPage: true
  });
  await exampleText.click();
  await mapText(page);
  await expect
    .poll(async () => (await savedTemplate(page, request, flow.id))?.bindings?.dokument)
    .toBe("{{step_1.output.text}}");
  await page.screenshot({ path: test.info().outputPath("word-mapping.png"), fullPage: true });
  await page.getByRole("button", { name: SOURCE }).click();
  await page.getByRole("option", { name: EMPTY }).click();
  await page.getByRole("button", { name: /^(Refresh|Uppdatera)$/ }).click();
  await expect(page.getByRole("button", { name: SOURCE })).toHaveText(
    /^(Leave empty|Lämna tomt)\s*$/
  );
  await expect
    .poll(async () => (await savedTemplate(page, request, flow.id))?.bindings?.dokument)
    .toBe("");
  await page.reload();
  await selectStep(page, TEMPLATE);
  if (!(await page.getByRole("button", { name: SOURCE }).isVisible()))
    await page.getByRole("button", { name: /^(Result|Resultat)\b/ }).click();
  await expect(page.getByRole("button", { name: SOURCE })).toHaveText(
    /^(Leave empty|Lämna tomt)\s*$/
  );
});

test("upload remains attached to its originating step while navigation stays usable", async ({
  page,
  request
}) => {
  const flow = await createFlow(page, request);
  await openTemplate(page, flow.id);
  let release!: () => void;
  const pending = new Promise<void>((resolve) => (release = resolve));
  let inspecting = false;
  await page.route(`**/api/v1/flows/${flow.id}/template-inspect/**`, async (route) => {
    inspecting = true;
    await pending;
    await route.continue();
  });
  try {
    await upload(page, "slow-template.docx");
    await expect.poll(() => inspecting).toBe(true);
    await selectStep(page, TEXT_STEP);
    await expect(page.getByRole("textbox", { name: /^(Step name|Stegnamn)\b/ })).toHaveValue(
      TEXT_STEP,
      { timeout: 1000 }
    );
  } finally {
    release();
  }
  await expect(page.getByRole("textbox", { name: /^(Step name|Stegnamn)\b/ })).toHaveValue(
    TEXT_STEP
  );
  await selectStep(page, TEMPLATE);
  if (!(await page.getByRole("button", { name: SOURCE }).isVisible()))
    await page.getByRole("button", { name: /^(Result|Resultat)\b/ }).click();
  await expect(page.getByRole("button", { name: SOURCE })).toBeVisible();
  await mapText(page);
  await expect
    .poll(async () => (await savedTemplate(page, request, flow.id))?.template_name)
    .toBe("slow-template.docx");
  const saved = await api(page, request, `/api/v1/flows/${flow.id}/`);
  expect(saved.steps[0].output_config?.template_asset_id).toBeUndefined();
  expect(saved.steps[0].output_type).toBe("text");
});

test("inspection failure preserves mappings and retries an uploaded asset without uploading again", async ({
  page,
  request
}) => {
  const flow = await createFlow(page, request);
  await openTemplate(page, flow.id);
  await upload(page);
  await mapText(page);
  await expect
    .poll(async () => (await savedTemplate(page, request, flow.id))?.bindings?.dokument)
    .toBe("{{step_1.output.text}}");
  await expect(page.locator('[data-sonner-toast][data-type="success"]')).toHaveCount(0);
  let failed = false;
  let uploads = 0;
  await page.route(`**/api/v1/flows/${flow.id}/**`, async (route) => {
    if (route.request().method() === "POST" && route.request().url().includes("/template-files/"))
      uploads += 1;
    if (!failed && route.request().url().includes("/template-inspect/")) {
      failed = true;
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ message: "Unavailable", eneo_error_code: 0 })
      });
    }
    await route.continue();
  });
  await upload(page, "second-template.docx");
  await expect(page.getByRole("button", { name: RETRY })).toBeVisible();
  await expect(
    page
      .locator('[data-sonner-toast][data-type="success"]')
      .filter({ hasText: /Template uploaded|Mallen laddades/ })
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: SOURCE })).toContainText(TEXT_STEP);
  await page.getByRole("button", { name: RETRY }).click();
  await expect(page.getByRole("button", { name: RETRY })).toHaveCount(0);
  await expect(page.getByRole("button", { name: SOURCE })).toBeFocused();
  expect(uploads).toBe(1);
  await expect
    .poll(async () => (await savedTemplate(page, request, flow.id))?.template_name)
    .toBe("second-template.docx");
  expect((await savedTemplate(page, request, flow.id)).bindings.dokument).toBe(
    "{{step_1.output.text}}"
  );
});

test("template fields stay usable on laptops, desktop and ultrawide displays with keyboard controls", async ({
  page,
  request
}) => {
  const flow = await createFlow(page, request, true);
  await openTemplate(page, flow.id);
  await upload(page);
  const source = page.getByRole("button", { name: SOURCE });
  await expect(source).toBeVisible();
  await source.focus();
  await source.press("Enter");
  await page.keyboard.press("End");
  await page.keyboard.press("Enter");
  await expect(source).toBeFocused();
  await expect
    .poll(async () => (await savedTemplate(page, request, flow.id))?.bindings?.dokument)
    .toBe("{{datum}}");
  await source.click();
  await page.getByRole("option", { name: /^(Field|Fält): brukarens_namn$/ }).click();
  await expect(
    page.getByText(/You selected a form field|Du har valt ett formulärfält/)
  ).toBeVisible();
  for (const [width, height] of [
    [1024, 768],
    [1440, 1000],
    [2560, 1080]
  ]) {
    await page.setViewportSize({ width, height });
    await source.scrollIntoViewIfNeeded();
    const bounds = await source.boundingBox();
    expect(bounds).toBeTruthy();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    const mapping = page
      .locator('[data-slot="card"]')
      .filter({
        has: page.getByRole("heading", { name: /^(Map template fields|Koppla fält i mallen)$/ })
      })
      .first();
    expect(
      await mapping.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)
    ).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`word-${width}.png`), fullPage: true });
  }
});

test("a browser-mapped template produces a downloadable Word document", async ({
  page,
  request
}) => {
  test.setTimeout(120000);
  const flow = await createFlow(page, request);
  const space = await api(page, request, "/api/v1/spaces/type/personal/");
  const model = space.completion_models.find((item: { name: string }) => item.name === "e2e-mock");
  expect(model).toBeTruthy();
  for (const step of flow.steps.slice(0, 2)) {
    const response = await backendFetch(
      page,
      request,
      `/api/v1/flows/${flow.id}/assistants/${step.assistant_id}/`,
      {
        method: "PATCH",
        data: {
          completion_model: { id: model.id },
          prompt: { text: "Return the provided source text." }
        }
      }
    );
    await expectOk(response, "setting the local test model");
  }
  await openTemplate(page, flow.id);
  await upload(page);
  await mapText(page);
  await expect
    .poll(async () => (await savedTemplate(page, request, flow.id))?.bindings?.dokument)
    .toBe("{{step_1.output.text}}");
  const published = await backendFetch(page, request, `/api/v1/flows/${flow.id}/publish/`, {
    method: "POST"
  });
  await expectOk(published, "publishing the local test fixture");
  await page.reload();
  await page.getByRole("button", { name: /^(Run flow|Kör flöde)$/ }).click();
  const dialog = page.getByRole("dialog", { name: /^(Run flow|Kör flöde)$/ });
  await dialog.getByRole("button", { name: /^(Next|Nästa)$/ }).click();
  await dialog
    .getByRole("textbox", { name: /^(Input|Indata|Material|Underlag)$/ })
    .fill("Source material for the existing Word template.");
  await dialog.getByRole("button", { name: /^(Next|Nästa)$/ }).click();
  await dialog.getByRole("button", { name: /^(Start run|Starta körning)$/ }).click();
  const history = page.locator("#panel-history");
  await expect(history).toBeVisible();
  await history.getByRole("button", { name: /^(View details|Visa detaljer)$/ }).click();
  const download = page.getByRole("button", { name: /^(Download|Ladda ner) .*\.docx$/ });
  await expect(download).toBeVisible({ timeout: 60000 });
  const downloadPromise = page.waitForEvent("download");
  await download.click();
  const result = await downloadPromise;
  expect(await result.failure()).toBeNull();
  await result.saveAs(test.info().outputPath("filled-word.docx"));
  const file = await readFile(test.info().outputPath("filled-word.docx"));
  expect(file.subarray(0, 4).toString("hex")).toBe("504b0304");
  const saved = await api(page, request, `/api/v1/flows/${flow.id}/runs/`);
  const run = (saved.items ?? saved)[0];
  const details = await api(page, request, `/api/v1/flows/${flow.id}/runs/${run.id}/`);
  expect(details.status).toBe("completed");
  expect(details.result_files[0].name).toMatch(/\.docx$/);
  const results = await api(page, request, `/api/v1/flows/${flow.id}/runs/${run.id}/steps/`);
  expect(JSON.stringify(results)).toContain(MOCK_REPLY);
  await page.screenshot({ path: test.info().outputPath("word-result.png"), fullPage: true });
});
