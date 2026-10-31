import { expect, test } from "./csp";
import type { Page } from "@playwright/test";
import type { Space } from "../src/features/spaces/space";
import {
  apiPost,
  apiPostJson,
  createSpace,
  openCreateCollectionDialog,
  sessionResponseHeaders,
  uniqueName
} from "./helpers";
import type { components } from "../src/lib/api/schema";

type Assistant = components["schemas"]["AssistantPublic"];
type Preflight = components["schemas"]["PreflightResponse"];

test("persists material modes and meters live instructions with native files and preflight", async ({
  page
}, testInfo) => {
  test.setTimeout(60_000);
  const space = await createSpace(page, uniqueName("Material"));
  const assistant = await apiPostJson<Assistant>(page, `${space}/applications/assistants/`, {
    name: uniqueName("Materialassistent")
  });
  const path = `/assistants/${assistant.id}/`;
  const editor = `${space}/assistants/${assistant.id}/edit`;
  await apiPost(page, path, { knowledge_mode: "tool", inline_file_text: false });
  await page.goto(`${editor}?section=knowledge`);
  await expect(page.getByRole("radio", { name: "Vid behov", exact: true })).toBeChecked();
  await expect(page.getByRole("radio", { name: "Öppna vid behov", exact: true })).toBeChecked();
  const settingsSaved = page.waitForResponse(
    (response) =>
      response.url().includes(path) &&
      response.request().method() === "POST" &&
      response.request().postDataJSON().knowledge_mode === "inject"
  );
  await page.getByRole("radio", { name: "Vid behov", exact: true }).press("ArrowDown");
  expect((await settingsSaved).ok()).toBe(true);
  await page.reload();
  await expect(page.getByRole("radio", { name: "Inför varje svar", exact: true })).toBeChecked();

  await page.goto(`${editor}?section=attachments`);
  const uploadSaved = page.waitForResponse(
    (response) =>
      response.url().includes(path) &&
      response.request().method() === "POST" &&
      response.request().postDataJSON().attachments?.length === 1
  );
  await page.locator('[data-editor-section="attachments"] input[type="file"]').setInputFiles({
    name: "native-material.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Öppettider måndag till fredag. Kontakt via kommunens reception.")
  });
  const attached: Assistant = await (await uploadSaved).json();
  expect((attached.attachments ?? [])[0]?.inline_text).toBe(false);
  await expect(page.getByText("Öppnas vid behov", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Ändra hur native-material.txt används" }).click();
  const inlineSaved = page.waitForResponse(
    (response) =>
      response.url().includes(path) &&
      response.request().method() === "POST" &&
      response.request().postDataJSON().attachments?.[0]?.inline_text === true
  );
  await page.getByRole("radio", { name: "Läs in inför varje svar", exact: true }).click();
  expect((await inlineSaved).ok()).toBe(true);
  await page.reload();
  await expect(page.getByText("Läses in inför varje svar", { exact: true })).toBeVisible();

  await page.goto(`${editor}?section=instructions`);
  const prompt = "Svara med stöd av det bifogade materialet.";
  const promptSaved = page.waitForResponse(
    (response) =>
      response.url().includes(path) &&
      response.request().method() === "POST" &&
      response.request().postDataJSON().prompt?.text === prompt
  );
  const preflightResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/conversations/preflight") &&
      response.ok() &&
      response.request().postDataJSON().assistant_prompt === prompt &&
      response.request().postDataJSON().attachments?.[0]?.inline_text === true
  );
  await page.locator("#assistant-prompt").fill(prompt);
  await page.locator("#assistant-prompt").blur();
  expect((await promptSaved).ok()).toBe(true);
  const estimate: Preflight = await (await preflightResponse).json();
  expect(estimate.file_tokens).toBeGreaterThan(0);
  expect(estimate.prompt_tokens).toBeGreaterThan(0);
  const used = estimate.file_tokens + (estimate.prompt_tokens ?? 0);
  const compact = new Intl.NumberFormat("sv-SE", {
    notation: "compact",
    maximumFractionDigits: 1
  }).format(used);
  await expect(page.getByRole("button", { name: /Kontextbudget:/ })).toContainText(compact);
  await page
    .locator('[data-editor-section="instructions"]')
    .screenshot({ path: testInfo.outputPath("native-meter.png") });

  await page.goto(`${space}/knowledge`);
  const dialog = await openCreateCollectionDialog(page);
  await dialog.getByLabel(/^(namn|name)$/i).fill(uniqueName("Materialkälla"));
  await dialog.getByRole("button", { name: /skapa samling|create collection/i }).click();
  await page.waitForURL(/\/knowledge\/collections\/[^/]+$/);
  const collectionId = new URL(page.url()).pathname.split("/").pop()!;
  await apiPost(page, path, { groups: [{ id: collectionId }] });
  await page.goto(`${space}/chat?type=assistant&id=${assistant.id}&tab=chat`);
  await page.getByRole("button", { name: /Kunskap:/ }).click();
  await expect(
    page.getByText("Innehåll från dessa källor infogas i varje meddelande.", { exact: true })
  ).toBeVisible();
});

test("meters real Skill context with an empty prompt and no files", async ({ page }) => {
  const space = await createSpace(page, uniqueName("Skill baseline"));
  const skill = await apiPostJson<components["schemas"]["SkillPublic"]>(page, `${space}/skills/`, {
    display_name: "Material instructions",
    description: "Native context baseline",
    instructions: "Use clear, specific language and explain the supporting evidence. ".repeat(40),
    slug: "material-baseline"
  });
  const assistant = await apiPostJson<Assistant>(page, `${space}/applications/assistants/`, {
    name: uniqueName("Skill-only assistant")
  });
  await apiPost(page, `/assistants/${assistant.id}/`, {
    prompt: { text: "" },
    attachments: [],
    skill_bindings: [
      {
        skill_id: skill.id,
        skill_revision_id: skill.current_revision_id,
        activation_mode: "always"
      }
    ]
  });
  const preflight = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/conversations/preflight") &&
      response.ok() &&
      response.request().postDataJSON().assistant_id === assistant.id
  );
  await page.goto(`${space}/assistants/${assistant.id}/edit?section=instructions`);
  const estimate: Preflight = await (await preflight).json();
  expect(estimate.skill_context_tokens).toBeGreaterThan(0);
  expect(estimate.prompt_tokens).toBeGreaterThanOrEqual(estimate.skill_context_tokens ?? 0);
  expect(estimate.file_tokens).toBe(0);
  expect((await preflight).request().postDataJSON().assistant_prompt).toBe("");
  const total = new Intl.NumberFormat("sv-SE", {
    notation: "compact",
    maximumFractionDigits: 1
  }).format(estimate.prompt_tokens ?? 0);
  await expect(page.getByRole("button", { name: /Kontextbudget:/ })).toContainText(`~${total}`);
  await expect(page.locator("#assistant-prompt")).toHaveValue("");
});

async function setPromptEnforcement(page: Page, promptId: string | null) {
  const body = {
    prompt_enforcement: { enabled: promptId !== null, prompt_library_id: promptId }
  } satisfies components["schemas"]["GovernancePolicyUpdate"];
  const result = await page.evaluate(async (body) => {
    const session = await fetch("/api/v1/auth/session/");
    const generation = session.headers.get("Eneo-Session-Generation");
    if (session.status !== 204 || !generation) throw new Error("Missing fixture session");
    const response = await fetch("/api/v1/admin/governance-policy/", {
      method: "PUT",
      headers: { "content-type": "application/json", "Eneo-Session-Generation": generation },
      body: JSON.stringify(body)
    });
    return { ok: response.ok, body: await response.text() };
  }, body);
  expect(result.ok, result.body).toBe(true);
}

test("uses the real governed prompt baseline without a stored prompt override", async ({
  page
}) => {
  test.setTimeout(60_000);
  await page.goto("/spaces/personal");
  const spaceResponse = await page.request.get("/api/v1/spaces/type/personal/");
  expect(spaceResponse.ok()).toBe(true);
  const personal: Space = await spaceResponse.json();
  const id = personal.default_assistant!.id;
  await apiPost(page, `/assistants/${id}/`, { prompt: { text: "Short stored prompt" } });
  const enforced = await apiPostJson<{ id: string }>(page, "/admin/prompt-library/", {
    name: uniqueName("Governed material"),
    description: "Native governed baseline",
    text: "Use the organisation instructions when answering and explain their scope. ".repeat(100)
  });
  await setPromptEnforcement(page, enforced.id);
  try {
    const input = { assistant_id: id, question: "", file_ids: [], attachments: [] };
    const baseline = await apiPostJson<Preflight>(page, "/conversations/preflight", input);
    const stored = await apiPostJson<Preflight>(page, "/conversations/preflight", {
      ...input,
      assistant_prompt: "Short stored prompt"
    });
    expect(baseline.prompt_tokens).toBeGreaterThan(stored.prompt_tokens ?? 0);
    const preflight = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/conversations/preflight") &&
        response.ok() &&
        response.request().postDataJSON().assistant_id === id
    );
    await page.goto(`/spaces/personal/assistants/${id}/edit?section=instructions`);
    const response = await preflight;
    expect(response.request().postDataJSON()).not.toHaveProperty("assistant_prompt");
    const estimate: Preflight = await response.json();
    expect(estimate.prompt_tokens).toBe(baseline.prompt_tokens);
    await expect(page.locator("#assistant-prompt")).toBeDisabled();
    const total = new Intl.NumberFormat("sv-SE", {
      notation: "compact",
      maximumFractionDigits: 1
    }).format(estimate.prompt_tokens ?? 0);
    await expect(page.getByRole("button", { name: /Kontextbudget:/ })).toContainText(`~${total}`);
  } finally {
    await setPromptEnforcement(page, null);
  }
});

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`material controls on a phone in ${colorScheme}`, () => {
    test.use({
      viewport: { width: 320, height: 800 },
      hasTouch: true,
      isMobile: true,
      colorScheme
    });
    test("fits mode controls and explains reserve warnings and advisory failures", async ({
      page
    }, testInfo) => {
      const space = await createSpace(page, uniqueName("Mobilmaterial"));
      const assistant = await apiPostJson<Assistant>(page, `${space}/applications/assistants/`, {
        name: uniqueName("Mobilassistent")
      });
      const editor = `${space}/assistants/${assistant.id}/edit`;
      const limit = assistant.completion_model?.max_input_tokens ?? 0;
      expect(limit).toBeGreaterThan(0);
      let phase: "near" | "over" | "error" = "near";
      // Fixture counts isolate reserve warnings; the first test verifies real tokenization.
      await page.route("**/api/v1/conversations/preflight", (route) =>
        route.fulfill({
          status: phase === "error" ? 503 : 200,
          headers: sessionResponseHeaders(route),
          json:
            phase === "error"
              ? { message: "Fixture unavailable" }
              : {
                  input_tokens: 0,
                  file_tokens: 0,
                  prompt_tokens: Math.floor(limit * (phase === "over" ? 0.8 : 0.7)),
                  context_window: limit,
                  context_reserve_tokens: Math.floor(limit * 0.25),
                  model_name: "Fixture"
                }
        })
      );
      await page.goto(`${editor}?section=instructions`);
      await page.locator("#assistant-prompt").fill("Native meter near");
      await expect(page.getByRole("button", { name: /Kontextbudget:/ })).toHaveClass(
        /text-warning/
      );
      phase = "over";
      await page.locator("#assistant-prompt").fill("Native meter over");
      await expect(
        page
          .locator('[data-editor-section="instructions"]')
          .getByText(/annars går assistenten inte att spara/)
      ).toBeVisible();
      await expect(page.getByRole("button", { name: /Kontextbudget:/ })).toHaveClass(
        /text-destructive/
      );
      await page.getByRole("button", { name: /Kontextbudget:/ }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath("phone-context.png"), fullPage: true });
      phase = "error";
      await page.locator("#assistant-prompt").fill("Native meter failure");
      await expect(
        page
          .locator('[data-editor-section="instructions"]')
          .getByText(/Kontexten kunde inte uppskattas/)
      ).toBeVisible();
      await expect(page.locator('[data-astryx-live-region="polite"]')).toContainText(
        "Kontexten kunde inte uppskattas"
      );
      await expect(page.locator("#assistant-prompt")).toBeEnabled();
      await expect(page.getByRole("button", { name: /Kontextbudget:/ })).toHaveCount(0);
      await page.goto(`${editor}?section=knowledge`);
      await expect(
        page.getByRole("radio", { name: "Inför varje svar", exact: true })
      ).toBeVisible();
      expect(
        await page.evaluate(
          () =>
            document.getElementById("main-content")!.scrollWidth -
            document.getElementById("main-content")!.clientWidth
        )
      ).toBeLessThanOrEqual(0);
      await page.screenshot({ path: testInfo.outputPath("phone-modes.png"), fullPage: true });
    });
  });
}
