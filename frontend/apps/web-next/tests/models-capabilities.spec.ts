import type { Locator, Page } from "@playwright/test";
import { expect, test } from "./csp";
import { apiPost, uniqueName } from "./helpers";

test.skip(!process.env.E2E_BASE_URL, "Verifies the model capability flags on FastAPI.");

/** The answer a model's details give for one property. */
const detailValue = (dialog: Locator, label: string) =>
  dialog
    .locator("dt", { hasText: new RegExp(`^${label}$`) })
    .locator("xpath=following-sibling::dd[1]");

/** A provider of `type` with one model of `kind`, opened on the models page. */
async function providerModel(
  page: Page,
  type: "vllm" | "openai",
  kind: "transcription" | "completion",
  model: object
) {
  await page.goto("/admin/models");
  const providerName = uniqueName(`E2E ${type}`);
  const displayName = uniqueName(`E2E ${kind}`);
  const providerId = await apiPost(page, "/admin/model-providers/", {
    name: providerName,
    provider_type: type,
    credentials: { api_key: "e2e-capability-fixture" },
    config: { endpoint: "http://e2e-mock-model:8200/v1" }
  });
  await apiPost(page, `/admin/tenant-models/${kind}/`, {
    provider_id: providerId,
    display_name: displayName,
    ...model
  });
  await page.goto("/admin/models");
  const provider = page.getByRole("region", { name: providerName, exact: true });
  const open = async () => {
    await provider.getByRole("button", { name: displayName, exact: true }).click();
    return page.getByRole("dialog", { name: displayName, exact: true });
  };
  const edit = async () => {
    await (await open()).getByRole("button", { name: "Redigera", exact: true }).click();
    return page.getByRole("dialog", { name: "Redigera modell", exact: true });
  };
  return { provider, open, edit };
}

async function save(dialog: Locator) {
  await dialog.getByRole("button", { name: "Spara", exact: true }).click();
  await expect(dialog).toBeHidden();
}

test(
  "an admin turns live transcription on and off for a vLLM transcription model",
  { tag: "@vite" },
  async ({ page }) => {
    const { provider, open, edit } = await providerModel(page, "vllm", "transcription", {
      name: uniqueName("e2e-live"),
      supports_realtime: false
    });
    let details = await open();
    await expect(detailValue(details, "Livetranskribering")).toHaveText("Nej");
    await page.keyboard.press("Escape");

    let form = await edit();
    await form.getByRole("switch", { name: "Livetranskribering", exact: true }).check();
    await save(form);
    // The backend accepted it for a vLLM provider and returns it.
    // The row lists its capabilities twice (column and under the name); the width shows one.
    await expect(
      provider.getByText("Livetranskribering", { exact: true }).filter({ visible: true })
    ).toBeVisible();
    details = await open();
    await expect(detailValue(details, "Livetranskribering")).toHaveText("Ja");
    await page.keyboard.press("Escape");

    form = await edit();
    await form.getByRole("switch", { name: "Livetranskribering", exact: true }).uncheck();
    await save(form);
    details = await open();
    await expect(detailValue(details, "Livetranskribering")).toHaveText("Nej");
  }
);

test(
  "live transcription cannot be turned on for a provider that is not vLLM",
  { tag: "@vite" },
  async ({ page }) => {
    const { edit } = await providerModel(page, "openai", "transcription", {
      name: uniqueName("e2e-whisper")
    });
    const form = await edit();
    await expect(
      form.getByRole("switch", { name: "Livetranskribering", exact: true })
    ).toBeDisabled();
    await expect(
      form.getByText("Kräver en leverantör av typen vLLM.", { exact: true })
    ).toBeVisible();
  }
);

test(
  "a strict tool-schema declaration is saved for its route and withdrawn when the route moves",
  { tag: "@vite" },
  async ({ page }) => {
    const route = uniqueName("e2e-route");
    const { open, edit } = await providerModel(page, "openai", "completion", {
      name: route,
      max_input_tokens: 128000,
      max_output_tokens: 4096,
      supports_tool_calling: true
    });
    let form = await edit();
    const strict = form.getByRole("switch", { name: "Strikta verktygsscheman", exact: true });
    await expect(strict).not.toBeChecked();
    await strict.check();
    await save(form);
    let details = await open();
    await expect(details.getByText("Strikta verktygsscheman", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");

    // Another identifier makes the declaration ineffective; saved untouched,
    // the server withdraws it for the moved route.
    form = await edit();
    await form.getByLabel("Modellidentifierare", { exact: true }).fill(`${route}-moved`);
    await expect(
      form.getByRole("switch", { name: "Strikta verktygsscheman", exact: true })
    ).not.toBeChecked();
    await save(form);
    details = await open();
    await expect(detailValue(details, "Modellidentifierare")).toHaveText(`${route}-moved`);
    await expect(details.getByText("Strikta verktygsscheman", { exact: true })).toHaveCount(0);
  }
);
