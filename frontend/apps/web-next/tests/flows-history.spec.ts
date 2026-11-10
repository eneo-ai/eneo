import { readFile } from "node:fs/promises";
import type { Page } from "@playwright/test";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { apiPost, apiRequest, MOCK_REPLY, sessionResponseHeaders, uniqueName } from "./helpers";

test.skip(!process.env.E2E_BASE_URL, "Verifies Flows on FastAPI serving the Vite build.");

const originalPrompt = "Sammanfatta underlaget. Behåll instruktionen HISTORIK-VERSION-ETT.";
const revisedPrompt = "Skriv en rubrik. Behåll instruktionen HISTORIK-VERSION-TVA.";
const stepName = "Sammanfatta underlag";
const count = new Intl.NumberFormat("sv");

// Real persistence and execution, using the completion provider already seeded in E2E.
async function historyFlow(page: Page, source?: { title: string; text: string }) {
  await page.goto("/spaces/list");
  const models = await apiRequest<Schema<"PaginatedResponse_CompletionModelPublic_">>(
    page,
    "/completion-models/"
  );
  const seededModel = models.items.find((item) => item.name === "e2e-mock");
  if (!seededModel?.provider_id) throw new Error("The E2E mock completion provider is missing");
  // Declare a test-specific setting on the mock route without changing the shared seed model.
  // This exercises persisted parameters, not temperature's effect on generated text.
  const model = await apiRequest<Schema<"CompletionModelPublic">>(
    page,
    "/admin/tenant-models/completion/",
    {
      method: "POST",
      body: {
        provider_id: seededModel.provider_id,
        name: uniqueName("e2e-history").replaceAll(" ", "-"),
        display_name: uniqueName("E2E history model"),
        max_input_tokens: 32768,
        max_output_tokens: 2048,
        model_kwargs_capabilities: {
          temperature: { supported: true, control: "slider", minimum: 0, maximum: 2, step: 0.01 }
        }
      } satisfies Schema<"TenantCompletionModelCreate">
    }
  );
  expect(model.supported_model_kwargs.temperature).toMatchObject({ supported: true });
  const spaceId = await apiPost(page, "/spaces/", { name: uniqueName("E2E history") });
  const space = await apiRequest<Schema<"SpacePublic">>(page, `/spaces/${spaceId}/`);
  expect(space.completion_models.some((item) => item.id === model.id)).toBe(true);
  let collectionId: string | undefined;
  let sourceId: string | undefined;
  if (source) {
    const embeddings = await apiRequest<Schema<"PaginatedResponse_EmbeddingModelPublic_">>(
      page,
      "/embedding-models/"
    );
    const embedding = embeddings.items.find((item) => item.name === "e2e-mock-embedding");
    if (!embedding) throw new Error("The E2E mock embedding model is missing");
    collectionId = await apiPost(page, `/spaces/${spaceId}/knowledge/groups/`, {
      name: uniqueName("Historikkällor"),
      embedding_model: { id: embedding.id }
    });
    // Text insertion embeds and persists the source before returning.
    const blobs = await apiRequest<Schema<"PaginatedResponse_InfoBlobPublic_">>(
      page,
      `/groups/${collectionId}/info-blobs/`,
      {
        method: "POST",
        body: { info_blobs: [{ text: source.text, metadata: { title: source.title } }] }
      }
    );
    expect(blobs.items).toHaveLength(1);
    sourceId = blobs.items[0]!.id;
  }
  const flow = await apiRequest<Schema<"FlowPublic">>(page, "/flows/", {
    method: "POST",
    body: { space_id: spaceId, name: uniqueName("Historikflöde") }
  });
  const saved = await apiRequest<Schema<"FlowPublic">>(page, `/flows/${flow.id}/editor/`, {
    method: "PATCH",
    body: {
      expected_revision: flow.draft_revision,
      definition: { metadata_json: { evidence_policy: { allow_export: false } } },
      new_steps: [
        {
          name: stepName,
          assistant: {
            groups: collectionId ? [{ id: collectionId }] : [],
            completion_model: { id: model.id },
            completion_model_kwargs: { temperature: 0.2 },
            prompt: { text: originalPrompt }
          },
          configuration: {
            input_source: "flow_input",
            input_type: "text",
            input_config: {
              runtime_input: { enabled: !!source, required: false, input_format: "document" }
            },
            output_mode: "pass_through",
            output_type: "text"
          }
        }
      ]
    } satisfies Schema<"FlowEditorUpdateRequest">
  });
  const published = await apiRequest<Schema<"FlowPublic">>(
    page,
    `/flows/${flow.id}/publish/?expected_revision=${saved.draft_revision}`,
    { method: "POST" }
  );
  return { published, url: `/spaces/${spaceId}/flows/${flow.id}`, sourceId };
}

async function completedRun(
  page: Page,
  flow: Schema<"FlowPublic">,
  label: string,
  file?: { name: string; text: string }
) {
  let run: Schema<"FlowRunPublic">;
  if (file) {
    await page.goto(`/spaces/${flow.space_id}/flows/${flow.id}`);
    await page.getByRole("button", { name: "Kör flödet", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: `Kör ${flow.name}`, exact: true });
    await dialog.locator('input[type="file"]').setInputFiles({
      name: file.name,
      mimeType: "text/plain",
      buffer: Buffer.from(file.text)
    });
    await expect(dialog.getByText(/^Uppladdad, /)).toBeVisible();
    await dialog.getByRole("textbox", { name: /^Namn i listan över körningar/ }).fill(label);
    await dialog.getByRole("button", { name: "Nästa", exact: true }).click();
    const created = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/flows/${flow.id}/runs/`) &&
        response.request().method() === "POST"
    );
    await dialog.getByRole("button", { name: "Starta körningen", exact: true }).click();
    const response = await created;
    expect(response.ok()).toBe(true);
    run = await response.json();
  } else {
    run = await apiRequest<Schema<"FlowRunPublic">>(page, `/flows/${flow.id}/runs/`, {
      method: "POST",
      body: {
        expected_flow_version: flow.published_version,
        run_label: label,
        input_payload_json: { text: "Ett kort underlag för historikkontrollen." }
      } satisfies Schema<"FlowRunCreateRequest">
    });
  }
  const path = `/flows/${flow.id}/runs/${run.id}`;
  await expect
    .poll(
      async () =>
        (await apiRequest<Schema<"FlowRunSummaryPublic">>(page, `${path}/status/`)).status,
      { timeout: 60_000 }
    )
    .toBe("completed");
  const detail = await apiRequest<Schema<"FlowRunDetailPublic">>(page, `${path}/`);
  const steps = await apiRequest<Schema<"FlowRunStepPublic">[]>(page, `${path}/steps/`);
  const evidence = await apiRequest<Schema<"FlowRunEvidenceResponse">>(page, `${path}/evidence/`);
  expect(steps).toHaveLength(1);
  expect(evidence.step_attempts).toHaveLength(1);
  return { detail, step: steps[0]!, evidence, path };
}

test(
  "opens an older run with its stored prompt, model usage and evidence after republishing",
  { tag: "@vite" },
  async ({ page, context }) => {
    test.setTimeout(150_000);
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const source = {
      title: uniqueName("Handbok för historikkontroll"),
      text: "Historikkontrollen använder ett sparat beslutsunderlag. Beslutet ska innehålla datum och ansvarig handläggare."
    };
    const file = {
      name: "historiskt-underlag.txt",
      text: "Sammanfatta beslutsunderlaget i handboken."
    };
    const { published, url, sourceId } = await historyFlow(page, source);
    const olderLabel = uniqueName("Äldre körning");
    const older = await completedRun(page, published, olderLabel, file);
    expect(older.step.runtime_input_files).toEqual([expect.objectContaining({ name: file.name })]);
    const reference = older.evidence.knowledge_traces?.[0]?.rag.references?.[0];
    expect(reference?.id).toBe(sourceId);
    expect(reference?.usage_state).toBe("inserted_into_prompt");
    expect(reference?.passages).toHaveLength(1);
    const passage = reference!.passages![0]!;
    expect(passage.text).toBe(source.text);
    expect(older.detail.evidence_access.can_export_redacted).toBe(false);
    expect(older.detail.evidence_access.redacted_export_refusal_code).toBe(
      "flow_run_evidence_export_disabled"
    );
    await page.goto(`${url}/runs/${older.detail.id}`);
    // The evidence and its export sit in a fold under the result.
    await page.getByRole("button", { name: "Bevisunderlag", exact: true }).click();
    await expect(
      page.getByText(/^Nedladdning av bevisunderlag är avstängd för flödet\./)
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Ladda ner bevisunderlag", exact: true })
    ).toHaveCount(0);

    const draft = await apiRequest<Schema<"FlowPublic">>(
      page,
      `/flows/${published.id}/unpublish/?expected_revision=${published.draft_revision}`,
      { method: "POST" }
    );
    const step = draft.steps[0]!;
    const saved = await apiRequest<Schema<"FlowPublic">>(page, `/flows/${draft.id}/editor/`, {
      method: "PATCH",
      body: {
        expected_revision: draft.draft_revision,
        definition: { metadata_json: { evidence_policy: { allow_export: true } } },
        assistants: [
          {
            assistant_id: step.assistant_id,
            step_id: step.id,
            changes: {
              groups: [],
              prompt: { text: revisedPrompt },
              completion_model_kwargs: { temperature: 0.7 }
            }
          }
        ]
      } satisfies Schema<"FlowEditorUpdateRequest">
    });
    const republished = await apiRequest<Schema<"FlowPublic">>(
      page,
      `/flows/${saved.id}/publish/?expected_revision=${saved.draft_revision}`,
      { method: "POST" }
    );
    const newerLabel = uniqueName("Nyare körning");
    const newer = await completedRun(page, republished, newerLabel);
    expect(newer.detail.flow_version).toBeGreaterThan(older.detail.flow_version);
    expect(newer.step.effective_prompt).toContain(revisedPrompt);
    expect(older.step.effective_prompt).toContain(originalPrompt);
    expect(older.step.effective_prompt).not.toContain(revisedPrompt);
    expect(older.step.model_parameters_json).toMatchObject({ temperature: 0.2 });
    expect(newer.step.model_parameters_json).toMatchObject({ temperature: 0.7 });
    expect(newer.step.runtime_input_file_ids ?? []).toHaveLength(0);
    expect(newer.evidence.knowledge_traces?.[0]?.rag.references ?? []).toHaveLength(0);

    // The table's usage column needs a full-width window beside the chat.
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto(`${url}?tab=runs`);
    await expect(page.getByRole("link", { name: newerLabel, exact: true })).toBeVisible();
    const oldLink = page.getByRole("link", { name: olderLabel, exact: true });
    const row = page.getByRole("row").filter({ has: oldLink });
    const usage = older.detail.token_usage!;
    expect(usage.num_tokens_total).toBeGreaterThan(0);
    expect(usage.input_completeness).toBe("complete");
    expect(usage.output_completeness).toBe("complete");
    const usageText = `${count.format(usage.num_tokens_total)} totalt (${count.format(usage.num_tokens_input)} in, ${count.format(usage.num_tokens_output)} ut)`;
    await expect(row.getByText(usageText, { exact: true })).toBeVisible();
    await oldLink.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(`${new URL(url, page.url()).href}/runs/${older.detail.id}`);
    // The router keeps the history on screen until the run's page has loaded (its route code
    // arrives on demand), and that table has this usage in both rows and the older row's
    // version: read the run's own page once it has replaced the list, never the outgoing table.
    await expect(
      page.getByRole("heading", { level: 1, name: olderLabel, exact: true })
    ).toBeVisible();
    await expect(page.getByRole("table", { name: "Körningar", exact: true })).toHaveCount(0);
    await expect(
      page.getByText(`Version ${older.detail.flow_version}`, { exact: true })
    ).toBeVisible();
    const usageFold = page.getByRole("region", { name: "Användning", exact: true });
    await usageFold.getByRole("button", { name: "Användning", exact: true }).click();
    await expect(usageFold.getByText(usageText, { exact: true })).toBeVisible();

    const article = page.getByRole("article", { name: `Steg 1: ${stepName}`, exact: true });
    await test.step("opens the older run's file and recorded knowledge passage after republishing", async () => {
      const inputs = article.getByRole("list", { name: "Filer som steget fick", exact: true });
      await expect(inputs.getByText(file.name, { exact: true })).toBeVisible();
      const downloaded = page.waitForEvent("download");
      await inputs.getByRole("button", { name: `Ladda ner ${file.name}`, exact: true }).click();
      const download = await downloaded;
      expect(download.suggestedFilename()).toBe(file.name);
      const path = await download.path();
      expect(path).not.toBeNull();
      expect(await readFile(path!, "utf8")).toBe(file.text);

      const knowledge = page.getByRole("region", { name: "Kunskapskällor", exact: true });
      await knowledge.getByRole("button", { name: "Kunskapskällor", exact: true }).click();
      await knowledge.getByRole("button", { name: "Visa kunskapsunderlag", exact: true }).click();
      const openSource = knowledge.getByRole("button", {
        name: `Visa källan ${source.title}`,
        exact: true
      });
      await openSource.focus();
      await page.keyboard.press("Enter");
      const viewer = page.getByRole("dialog", { name: source.title, exact: true });
      const document = viewer.getByRole("region", {
        name: `Dokumentet ${source.title}`,
        exact: true
      });
      await expect(document).toHaveText(source.text);
      const highlight = document.locator("mark");
      await expect(highlight).toHaveText(passage.text!);
      const next = viewer.getByRole("button", { name: "Nästa träff", exact: true });
      await next.focus();
      await page.keyboard.press("Enter");
      await expect(highlight).toBeFocused();
      await expect(viewer.getByText("1 av 1", { exact: true })).toBeVisible();
      await viewer.screenshot({
        path: test.info().outputPath("flow-history-knowledge-passage.png")
      });
      await viewer.getByRole("button", { name: "Klar", exact: true }).click();
      await expect(viewer).toBeHidden();
      await expect(openSource).toBeFocused();
      await expect(page).toHaveURL(`${new URL(url, page.url()).href}/runs/${older.detail.id}`);
    });
    expect(older.step.num_tokens_input).toBeGreaterThan(0);
    expect(older.step.num_tokens_output).toBeGreaterThan(0);
    await expect(article).toContainText(
      `${count.format(older.step.num_tokens_input! + older.step.num_tokens_output!)} token (${count.format(older.step.num_tokens_input!)} in, ${count.format(older.step.num_tokens_output!)} ut)`
    );
    await test.step("expands and copies the secondary step result without hiding the main result", async () => {
      const output = older.step.output_payload_json?.text;
      expect(output).toBe(MOCK_REPLY);
      const primary = page
        .getByRole("region", { name: "Resultat", exact: true })
        .getByText(MOCK_REPLY, { exact: true });
      const secondary = article.getByText(MOCK_REPLY, { exact: true });
      const disclosure = article.getByRole("button", { name: "Stegets resultat", exact: true });
      const copy = article.getByRole("button", { name: "Kopiera resultatet", exact: true });
      await expect(disclosure).toHaveAttribute("aria-expanded", "false");
      await expect(secondary).toHaveCount(0);
      await expect(primary).toHaveCount(1);
      await expect(primary).toBeVisible();
      await expect(copy).toBeVisible();
      await disclosure.focus();
      await page.keyboard.press("Enter");
      await expect(disclosure).toHaveAttribute("aria-expanded", "true");
      await expect(disclosure).toBeFocused();
      await expect(secondary).toHaveCount(1);
      await expect(secondary).toBeVisible();
      await expect(primary).toHaveCount(1);
      await expect(primary).toBeVisible();
      await page.screenshot({
        path: test.info().outputPath("flow-step-output-expanded.png"),
        fullPage: true
      });
      await copy.click();
      await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(output);
      await disclosure.focus();
      await page.keyboard.press("Enter");
      await expect(disclosure).toHaveAttribute("aria-expanded", "false");
      await expect(disclosure).toBeFocused();
      await expect(secondary).toBeHidden();
      await expect(primary).toHaveCount(1);
      await expect(primary).toBeVisible();
      await expect(copy).toBeVisible();
    });
    await article
      .getByRole("button", { name: "Prompt och modellinställningar", exact: true })
      .click();
    await expect(article.locator("pre")).toHaveText(older.step.effective_prompt!);
    await expect(
      article
        .locator("dt")
        .filter({ hasText: /^Temperatur$/ })
        .first()
        .locator("+ dd")
    ).toHaveText("0.2");
    await article.getByRole("button", { name: "Kopiera prompten", exact: true }).click();
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(older.step.effective_prompt);
    // The attempts are part of the evidence, folded under the result and loaded on request.
    await page.getByRole("button", { name: "Bevisunderlag", exact: true }).click();
    await page.getByRole("button", { name: "Visa bevisunderlag", exact: true }).click();
    const attempts = page.getByRole("region", { name: "Försök per steg", exact: true });
    const attempt = older.evidence.step_attempts[0]!;
    expect(attempt.response_model || attempt.requested_model).toBeTruthy();
    await expect(
      attempts.getByText(`Modell ${attempt.response_model || attempt.requested_model}`, {
        exact: false
      })
    ).toBeVisible();
    await attempts.getByRole("button", { name: "Detaljer för försök 1", exact: true }).click();
    await attempts.getByRole("button", { name: "Kopiera försök 1", exact: true }).click();
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(JSON.stringify(attempt, null, 2));

    const access = await apiRequest<Schema<"FlowRunDetailPublic">>(page, `${older.path}/`);
    expect(access.evidence_access.can_export_redacted).toBe(true);
    const downloaded = page.waitForEvent("download");
    await page
      .getByRole("region", { name: "Bevisunderlag", exact: true })
      .getByRole("button", { name: "Ladda ner bevisunderlag", exact: true })
      .click();
    const download = await downloaded;
    expect(await download.failure()).toBeNull();
    const exported = JSON.parse(
      await readFile((await download.path())!, "utf8")
    ) as Schema<"FlowRunEvidenceExportResponse">;
    expect(exported.schema_version).toBe("flow-evidence-export.v18");
    expect(exported.manifest).toMatchObject({
      run_id: older.detail.id,
      flow_id: published.id,
      flow_version: older.detail.flow_version,
      detail_mode: "redacted"
    });
    await page.screenshot({
      path: test.info().outputPath("flow-history-stored-run.png"),
      fullPage: true
    });
    await page
      .getByRole("navigation", { name: "Sökväg", exact: true })
      .getByRole("link", { name: published.name, exact: true })
      .click();
    await expect(page).toHaveURL(`${new URL(url, page.url()).href}?tab=runs`);
    await expect(page.getByRole("link", { name: olderLabel, exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: newerLabel, exact: true })).toBeVisible();
  }
);

test(
  "renders and copies separate attempts with missing and partial usage from an evidence fixture",
  { tag: "@vite" },
  async ({ page, context }) => {
    test.setTimeout(90_000);
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const { published, url } = await historyFlow(page);
    const run = await completedRun(page, published, uniqueName("Försöksvisning"));
    const original = run.evidence.step_attempts[0]!;
    // Only the evidence read is replaced. This proves rendering/copying, not a real provider retry.
    const attempts: Schema<"FlowStepAttemptPublic">[] = [
      {
        ...original,
        id: "00000000-0000-4000-8000-000000000001",
        attempt_no: 1,
        status: "failed",
        requested_model: "fixture-requested",
        response_model: null,
        num_tokens_input: null,
        num_tokens_output: null,
        finish_reason: null,
        error_code: "flow_provider_unavailable"
      },
      {
        ...original,
        id: "00000000-0000-4000-8000-000000000002",
        attempt_no: 2,
        status: "completed",
        requested_model: "fixture-requested",
        response_model: "fixture-response",
        num_tokens_input: 7,
        num_tokens_output: null
      }
    ];
    await page.route(`**/api/v1${run.path}/evidence/`, async (route) => {
      await route.fulfill({
        headers: sessionResponseHeaders(route),
        json: {
          ...run.evidence,
          step_attempts: attempts
        } satisfies Schema<"FlowRunEvidenceResponse">
      });
    });
    await page.goto(`${url}/runs/${run.detail.id}`);
    await page.getByRole("button", { name: "Bevisunderlag", exact: true }).click();
    await page.getByRole("button", { name: "Visa bevisunderlag", exact: true }).click();
    const attemptList = page
      .getByRole("region", { name: "Försök per steg", exact: true })
      .getByRole("list", { name: `Steg 1: ${stepName}`, exact: true });
    const first = attemptList
      .getByRole("listitem")
      .filter({ has: page.getByText("Försök 1", { exact: true }) });
    const second = attemptList
      .getByRole("listitem")
      .filter({ has: page.getByText("Försök 2", { exact: true }) });
    await expect(first).toContainText("Modell fixture-requested");
    await expect(first).toContainText("Tokenanvändningen registrerades inte");
    await expect(second).toContainText("Modell fixture-response");
    await expect(second).toContainText("7 token (7 in, – ut)");
    await expect(second).toContainText("(ofullständigt)");
    const details = second.getByRole("button", { name: "Detaljer för försök 2", exact: true });
    await details.focus();
    await page.keyboard.press("Enter");
    await expect(details).toHaveAttribute("aria-expanded", "true");
    await expect(details).toBeFocused();
    await second.getByRole("button", { name: "Kopiera försök 2", exact: true }).click();
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(JSON.stringify(attempts[1], null, 2));
    await details.focus();
    await page.keyboard.press("Enter");
    await expect(details).toHaveAttribute("aria-expanded", "false");
    await expect(details).toBeFocused();
    await expect(
      first.getByRole("button", { name: "Detaljer för försök 1", exact: true })
    ).toHaveAttribute("aria-expanded", "false");
  }
);
