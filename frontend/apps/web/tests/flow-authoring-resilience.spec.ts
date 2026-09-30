import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { FlowStep } from "@eneo/eneo-js";
import { backendFetch, expectOk, uniqueName } from "./helpers";

const STEP_NAME = /^(Step name|Stegnamn)\b/;
const INSTRUCTION = /^(Instruction for the AI|Instruktion till AI:n)$/;
const PROCESSING = /^4\. (Processing steps|Bearbetningssteg)/;
const TRANSCRIPTION = /^2\. (Transcription|Transkribering)/;
const EXPORT = /^(Export|Exportera)$/;
const IMPORT = /^(Import|Importera)$/;

async function api(page: Page, request: APIRequestContext, path: string, data?: object) {
  const response = await backendFetch(page, request, path, {
    method: data ? "POST" : "GET",
    ...(data ? { data } : {})
  });
  await expectOk(response, path);
  return response.json();
}

async function createFlow(page: Page, request: APIRequestContext) {
  const space = await api(page, request, "/api/v1/spaces/type/personal/");
  const flow = await api(page, request, "/api/v1/flows/", {
    space_id: space.id,
    name: uniqueName("E2E resilient authoring"),
    steps: [],
    metadata_json: { wizard: { transcription_enabled: false } }
  });
  const steps = [];
  for (let index = 1; index <= 8; index += 1) {
    const assistant = await api(page, request, `/api/v1/flows/${flow.id}/assistants/`, {
      name: `Resilience step ${index}`
    });
    const response = await backendFetch(
      page,
      request,
      `/api/v1/flows/${flow.id}/assistants/${assistant.id}/`,
      { method: "PATCH", data: { prompt: { text: `Preserve source text for step ${index}.` } } }
    );
    await expectOk(response, "setting instruction");
    steps.push({
      assistant_id: assistant.id,
      step_order: index,
      user_description: `Resilience step ${index}`,
      input_source: index === 1 ? "flow_input" : "previous_step",
      input_type: "text",
      output_mode: "pass_through",
      output_type: "text",
      ...(index === 3
        ? { output_config: { retrieval_policy: { version: 1, mode: "fail_closed" } } }
        : {})
    });
  }
  const response = await backendFetch(page, request, `/api/v1/flows/${flow.id}/`, {
    method: "PATCH",
    data: { steps, expected_revision: flow.draft_revision }
  });
  await expectOk(response, "saving eight-step flow");
  return response.json();
}

test("step navigation remains usable during slow flow and instruction saves", async ({
  page,
  request
}) => {
  const flow = await createFlow(page, request);
  await page.goto(`/spaces/personal/flows/${flow.id}?stage=4`);
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("textbox", { name: INSTRUCTION })).toBeVisible();

  let release!: () => void;
  const pending = new Promise<void>((resolve) => (release = resolve));
  let flowSaving = false;
  let assistantSaving = false;
  await page.route(`**/api/v1/flows/${flow.id}/**`, async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() === "PATCH") {
      if (url.pathname === `/api/v1/flows/${flow.id}/`) flowSaving = true;
      else if (url.pathname.includes(`/assistants/${flow.steps[0].assistant_id}/`))
        assistantSaving = true;
      else return route.continue();
      await pending;
    }
    await route.continue();
  });

  const instruction = "Keep this complete instruction. ".repeat(500);
  try {
    await page.getByRole("textbox", { name: INSTRUCTION }).fill(instruction);
    await page.getByRole("textbox", { name: STEP_NAME }).fill("Renamed while saving");
    await expect.poll(() => flowSaving && assistantSaving).toBe(true);

    await page
      .getByRole("listitem")
      .filter({ hasText: "Resilience step 2" })
      .getByRole("button")
      .first()
      .click();
    await expect(page.getByRole("textbox", { name: STEP_NAME })).toHaveValue("Resilience step 2", {
      timeout: 1000
    });
    await expect(page.getByRole("textbox", { name: INSTRUCTION })).toHaveValue(
      "Preserve source text for step 2.",
      { timeout: 1000 }
    );
    await page.getByRole("button", { name: TRANSCRIPTION, exact: true }).click();
    await expect(page.locator("#transcription-toggle")).toBeVisible({ timeout: 1000 });
    await page.getByRole("button", { name: PROCESSING, exact: true }).click();
    await expect(page.getByRole("textbox", { name: STEP_NAME })).toHaveValue("Resilience step 2");
  } finally {
    release();
  }

  await expect
    .poll(async () => {
      const saved = await api(page, request, `/api/v1/flows/${flow.id}/`);
      return saved.steps[0].user_description;
    })
    .toBe("Renamed while saving");
  await expect
    .poll(async () => {
      const assistant = await api(
        page,
        request,
        `/api/v1/flows/${flow.id}/assistants/${flow.steps[0].assistant_id}/`
      );
      return assistant.prompt.text;
    })
    .toBe(instruction);
  const nextAssistant = await api(
    page,
    request,
    `/api/v1/flows/${flow.id}/assistants/${flow.steps[1].assistant_id}/`
  );
  expect(nextAssistant.prompt.text).toBe("Preserve source text for step 2.");
});

test("exported flow imports as a draft with text-step uploads, retrieval policy and instructions", async ({
  page,
  request
}) => {
  const flow = await createFlow(page, request);
  const runtimeInput = {
    runtime_input: {
      enabled: true,
      required: false,
      input_format: "document",
      max_files: 3,
      label: "Additional documents"
    }
  };
  const uploadResponse = await backendFetch(page, request, `/api/v1/flows/${flow.id}/`, {
    method: "PATCH",
    data: {
      expected_revision: flow.draft_revision,
      steps: flow.steps.map((step: FlowStep) => ({
        id: step.id,
        assistant_id: step.assistant_id,
        step_order: step.step_order,
        user_description: step.user_description,
        input_source: step.input_source,
        input_type: step.input_type,
        output_mode: step.output_mode,
        output_type: step.output_type,
        input_config: step.step_order === 2 ? runtimeInput : step.input_config,
        output_config: step.output_config
      }))
    }
  });
  await expectOk(uploadResponse, "enabling optional documents on the second text step");
  await page.goto(`/spaces/personal/flows/${flow.id}?stage=4`);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: EXPORT, exact: true }).click();
  const exportDialog = page.getByRole("dialog", {
    name: /^(Export flow package|Exportera flödespaket)$/
  });
  const downloaded = page.waitForEvent("download");
  await exportDialog.getByRole("button", { name: EXPORT, exact: true }).click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toMatch(/\.eneopkg$/);
  const filePath = test.info().outputPath("round-trip.eneopkg");
  await download.saveAs(filePath);

  await page.goto("/spaces/personal/flows");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: IMPORT, exact: true }).click();
  const importDialog = page.getByRole("dialog", {
    name: /^(Import flow package|Importera flödespaket)$/
  });
  const invalidPlan = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/flow-packages/import-plan/") &&
      response.status() >= 400
  );
  await importDialog.locator('input[type="file"]').setInputFiles({
    name: "invalid.eneopkg",
    mimeType: "application/vnd.eneo.package+zip",
    buffer: Buffer.from("Invalid package bytes")
  });
  await invalidPlan;
  await expect(
    importDialog.getByRole("button", {
      name: /^(Import as draft|Importera som utkast)$/
    })
  ).toBeDisabled();
  await importDialog.locator('input[type="file"]').setInputFiles(filePath);
  const importButton = importDialog.getByRole("button", {
    name: /^(Import as draft|Importera som utkast)$/
  });
  await expect(importButton).toBeDisabled();
  await importDialog
    .getByRole("button", { name: /^(Choose local resource|Välj lokal resurs)$/ })
    .click();
  await page.getByRole("option", { name: "E2E Mock", exact: true }).click();
  await expect(importButton).toBeEnabled();
  await importButton.click();
  await page.waitForURL(/\/spaces\/[^/]+\/flows\/[^/?]+/);
  const importedId = new URL(page.url()).pathname.split("/").pop();
  expect(importedId).not.toBe(flow.id);
  const imported = await api(page, request, `/api/v1/flows/${importedId}/`);
  expect(imported.published_version).toBeNull();
  expect(imported.steps).toHaveLength(8);
  expect(imported.steps[1].input_config).toEqual(runtimeInput);
  expect(imported.steps[2].output_config.retrieval_policy).toEqual({
    version: 1,
    mode: "fail_closed"
  });
  for (const step of imported.steps) {
    const assistant = await api(
      page,
      request,
      `/api/v1/flows/${importedId}/assistants/${step.assistant_id}/`
    );
    expect(assistant.prompt.text).toBe(`Preserve source text for step ${step.step_order}.`);
  }
});

test("a rejected transcription save does not trap the author away from the fix", async ({
  page,
  request
}) => {
  const flow = await createFlow(page, request);
  const providers = await api(page, request, "/api/v1/admin/model-providers/");
  const model = await api(page, request, "/api/v1/admin/tenant-models/transcription/", {
    provider_id: providers[0].id,
    name: uniqueName("e2e-authoring-transcription"),
    display_name: uniqueName("E2E authoring transcription"),
    is_default: false
  });
  const audioFlowResponse = await backendFetch(page, request, `/api/v1/flows/${flow.id}/`, {
    method: "PATCH",
    data: {
      expected_revision: flow.draft_revision,
      steps: flow.steps.map((step: FlowStep) => ({
        id: step.id,
        assistant_id: step.assistant_id,
        step_order: step.step_order,
        user_description: step.user_description,
        input_source: step.input_source,
        input_type: step.step_order === 1 ? "audio" : step.input_type,
        output_mode: step.output_mode,
        output_type: step.output_type,
        output_config: step.output_config
      })),
      metadata_json: {
        wizard: { transcription_enabled: true, transcription_model: { id: model.id } }
      }
    }
  });
  await expectOk(audioFlowResponse, "setting up an audio flow");
  await page.goto(`/spaces/personal/flows/${flow.id}?stage=2`);
  await page.waitForLoadState("networkidle");
  const rejectedSave = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === `/api/v1/flows/${flow.id}/` &&
      response.request().method() === "PATCH" &&
      response.status() === 400
  );
  await page.locator("#transcription-toggle").click();
  const rejection = await rejectedSave;
  expect((await rejection.json()).code).toBe("flow_audio_transcription_required");

  await page.getByRole("button", { name: PROCESSING }).click();
  await expect(page.getByRole("textbox", { name: STEP_NAME })).toHaveValue("Resilience step 1", {
    timeout: 1000
  });
  await page.getByRole("tab", { name: /^(Advanced|Avancerad)$/ }).click();
  await page.getByRole("button", { name: /^(Material|Underlag)\b/ }).click();
  await page.getByRole("button", { name: /^(Material type|Typ av underlag)$/ }).click();
  await page.getByRole("option", { name: "Text", exact: true }).click();
  await expect
    .poll(async () => {
      const saved = await api(page, request, `/api/v1/flows/${flow.id}/`);
      return [saved.steps[0].input_type, saved.metadata_json.wizard.transcription_enabled];
    })
    .toEqual(["text", false]);
  await page.getByRole("button", { name: TRANSCRIPTION }).click();
  await expect(page.locator("#transcription-toggle")).toHaveAttribute("aria-checked", "false");
  await page.reload();
  await expect(page.locator("#transcription-toggle")).toHaveAttribute("aria-checked", "false");
});
