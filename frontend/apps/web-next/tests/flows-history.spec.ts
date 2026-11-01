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
async function historyFlow(page: Page) {
  await page.goto("/spaces/list");
  const spaceId = await apiPost(page, "/spaces/", { name: uniqueName("E2E history") });
  const space = await apiRequest<Schema<"SpacePublic">>(page, `/spaces/${spaceId}/`);
  const model = space.completion_models.find((item) => item.name === "e2e-mock");
  if (!model) throw new Error("The E2E space has no seeded e2e-mock completion model");
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
            completion_model: { id: model.id },
            completion_model_kwargs: { temperature: 0.2 },
            prompt: { text: originalPrompt }
          },
          configuration: {
            input_source: "flow_input",
            input_type: "text",
            output_mode: "compose_text",
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
  return { published, url: `/spaces/${spaceId}/flows/${flow.id}` };
}

async function completedRun(page: Page, flow: Schema<"FlowPublic">, label: string) {
  const run = await apiRequest<Schema<"FlowRunPublic">>(page, `/flows/${flow.id}/runs/`, {
    method: "POST",
    body: {
      expected_flow_version: flow.published_version,
      run_label: label,
      input_payload_json: { text: "Ett kort underlag för historikkontrollen." }
    } satisfies Schema<"FlowRunCreateRequest">
  });
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
    const { published, url } = await historyFlow(page);
    const olderLabel = uniqueName("Äldre körning");
    const older = await completedRun(page, published, olderLabel);
    expect(older.detail.evidence_access.can_export_redacted).toBe(false);
    expect(older.detail.evidence_access.redacted_export_refusal_code).toBe(
      "flow_run_evidence_export_disabled"
    );
    await page.goto(`${url}/runs/${older.detail.id}`);
    await expect(page.getByText(/^Export av bevisunderlag är avstängd för flödet\./)).toBeVisible();
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
    await expect(
      page.getByText(`Version ${older.detail.flow_version}`, { exact: true })
    ).toBeVisible();
    await expect(page.getByText(usageText, { exact: true })).toBeVisible();

    const article = page.getByRole("article", { name: `Steg 1: ${stepName}`, exact: true });
    expect(older.step.num_tokens_input).toBeGreaterThan(0);
    expect(older.step.num_tokens_output).toBeGreaterThan(0);
    await expect(article).toContainText(
      `${count.format(older.step.num_tokens_input! + older.step.num_tokens_output!)} token (${count.format(older.step.num_tokens_input!)} in, ${count.format(older.step.num_tokens_output!)} ut)`
    );
    await test.step("expands and copies the secondary step result without hiding the main result", async () => {
      const output = older.step.output_payload_json?.text;
      expect(output).toBe(MOCK_REPLY);
      const results = page.getByText(MOCK_REPLY, { exact: true });
      const secondary = article.getByText(MOCK_REPLY, { exact: true });
      const disclosure = article.getByRole("button", { name: "Stegets resultat", exact: true });
      const copy = article.getByRole("button", { name: "Kopiera resultatet", exact: true });
      await expect(disclosure).toHaveAttribute("aria-expanded", "false");
      await expect(secondary).toHaveCount(0);
      await expect(results).toHaveCount(1);
      await expect(results).toBeVisible();
      await expect(copy).toBeVisible();
      await disclosure.focus();
      await page.keyboard.press("Enter");
      await expect(disclosure).toHaveAttribute("aria-expanded", "true");
      await expect(disclosure).toBeFocused();
      await expect(secondary).toBeVisible();
      await expect(results).toHaveCount(2);
      await expect(results.first()).toBeVisible();
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
      await expect(secondary).toHaveCount(0);
      await expect(results).toHaveCount(1);
      await expect(results).toBeVisible();
      await expect(copy).toBeVisible();
    });
    await article
      .getByRole("button", { name: "Prompt och modellinställningar", exact: true })
      .click();
    await expect(article.locator("pre")).toHaveText(older.step.effective_prompt!);
    await expect(
      article
        .locator("dt")
        .filter({ hasText: /^temperature$/ })
        .first()
        .locator("+ dd")
    ).toHaveText("0.2");
    await article.getByRole("button", { name: "Kopiera prompten", exact: true }).click();
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(older.step.effective_prompt);
    await article.getByRole("button", { name: "Försök", exact: true }).click();
    const attempt = older.evidence.step_attempts[0]!;
    expect(attempt.response_model || attempt.requested_model).toBeTruthy();
    await expect(
      article.getByText(`Modell ${attempt.response_model || attempt.requested_model}`, {
        exact: false
      })
    ).toBeVisible();
    await article.getByRole("button", { name: "Detaljer för försök 1", exact: true }).click();
    await article.getByRole("button", { name: "Kopiera försök 1", exact: true }).click();
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(JSON.stringify(attempt, null, 2));

    const access = await apiRequest<Schema<"FlowRunDetailPublic">>(page, `${older.path}/`);
    expect(access.evidence_access.can_export_redacted).toBe(true);
    const downloaded = page.waitForEvent("download");
    await page.getByRole("button", { name: "Ladda ner bevisunderlag", exact: true }).click();
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
    await page.getByRole("link", { name: published.name, exact: true }).click();
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
    const article = page.getByRole("article", { name: `Steg 1: ${stepName}`, exact: true });
    await article.getByRole("button", { name: "Försök", exact: true }).click();
    const first = article
      .getByRole("listitem")
      .filter({ has: page.getByText("Försök 1", { exact: true }) });
    const second = article
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
