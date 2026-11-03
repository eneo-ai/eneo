import type { Page, Route } from "@playwright/test";
import { expect, test } from "./csp";
import { sessionResponseHeaders } from "./helpers";
import type { CompletionModelAdmin, ModelsPresentation } from "../src/features/admin/models/models";

const classification = {
  id: "class-internal",
  name: "Intern",
  description: null,
  security_level: 2
};
const source: CompletionModelAdmin = {
  id: "model-source",
  name: "provider/model-source",
  nickname: "Zeta fixture",
  provider_id: "provider-fixture",
  provider_type: "openai",
  is_org_enabled: true,
  is_org_default: true,
  is_locked: false,
  is_deprecated: false,
  // Inside the six-month window in which a coming deprecation is shown.
  deprecation_date: new Date(Date.now() + 30 * 86_400_000).toISOString().slice(0, 10),
  token_limit: 128000,
  supported_model_kwargs: {},
  max_input_tokens: 128000,
  max_output_tokens: 4096,
  vision: true,
  reasoning: true,
  supports_tool_calling: true,
  hosting: "usa",
  family: "gpt",
  org: "OpenAI",
  open_source: false,
  security_classification: classification,
  input_cost_per_token: "0.000005",
  output_cost_per_token: "0.00001"
};

async function fixtures(page: Page) {
  const writes: unknown[] = [];
  const models: ModelsPresentation = {
    completion_models: [
      source,
      {
        ...source,
        id: "model-compatible",
        nickname: "Alfa fixture",
        name: "provider/model-compatible",
        vision: false,
        deprecation_date: null,
        is_org_default: false
      },
      {
        ...source,
        id: "model-security",
        nickname: "Public fixture",
        name: "provider/model-security",
        security_classification: null,
        deprecation_date: null,
        is_org_default: false
      },
      {
        ...source,
        id: "model-historical",
        nickname: "Historical fixture",
        migrated_to_model_id: "model-compatible",
        is_org_enabled: false
      }
    ],
    embedding_models: [],
    transcription_models: [],
    image_models: [],
    rerank_models: []
  };
  const fulfill = (route: Route, json: unknown) =>
    route.fulfill({ json, headers: sessionResponseHeaders(route) });
  await page.route("**/api/v1/ai-models/", (route) => fulfill(route, models));
  await page.route("**/api/v1/admin/model-providers/", (route) =>
    fulfill(route, [
      {
        id: "provider-fixture",
        tenant_id: "fixture-tenant",
        name: "Fixture provider",
        provider_type: "openai",
        config: {},
        is_active: true,
        masked_api_key: "...fixture",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z"
      }
    ])
  );
  await page.route("**/api/v1/admin/model-providers/capabilities/", (route) =>
    fulfill(route, {
      providers: { openai: { modes: ["completion", "embedding"], fields: [], models: {} } },
      default_fields: []
    })
  );
  await page.route("**/api/v1/admin/model-providers/favorites/", (route) => fulfill(route, []));
  await page.route("**/api/v1/security-classifications/", (route) =>
    fulfill(route, { security_enabled: true, security_classifications: [classification] })
  );
  await page.route("**/api/v1/admin/model-providers/provider-fixture/models/**", (route) =>
    fulfill(route, [{ name: "multilingual-e5-large", output_vector_size: 1024, mode: "embedding" }])
  );
  await page.route("**/api/v1/admin/model-providers/provider-fixture/validate-model/", (route) =>
    fulfill(route, { success: true })
  );
  await page.route("**/api/v1/admin/tenant-models/**", (route) => {
    writes.push(route.request().postDataJSON());
    return fulfill(
      route,
      route.request().method() === "PUT"
        ? source
        : {
            id: "created-model",
            name: "multilingual-e5-large",
            nickname: "E5",
            family: "e5",
            hosting: "swe",
            is_org_enabled: true,
            is_deprecated: false,
            open_source: true,
            dimensions: 1024
          }
    );
  });
  await page.route("**/api/v1/completion-models/migration-history", (route) => fulfill(route, []));
  await page.route("**/api/v1/transcription-models/migration-history", (route) =>
    fulfill(route, [])
  );
  const entities = [
    ["assistant", "Upphandling"],
    ["app", "Protokoll"],
    ["service", "Ärendesortering"],
    ["assistant_template", "Avtalsgranskning"],
    ["app_template", "Mötesmall"]
  ].map(([entity_type, entity_name], index) => ({
    entity_id: String(index),
    entity_type,
    entity_name,
    space_name: "Kommunen",
    owner_name: "Anna"
  }));
  await page.route("**/api/v1/completion-models/model-source/usage", (route) =>
    fulfill(route, {
      model_id: source.id,
      total_usage: 6,
      assistants_count: 1,
      apps_count: 1,
      services_count: 1,
      assistant_templates_count: 1,
      app_templates_count: 1,
      spaces_count: 1,
      questions_count: 0,
      last_updated: "2026-01-01T00:00:00Z"
    })
  );
  await page.route("**/api/v1/completion-models/model-source/usage/details", (route) =>
    fulfill(route, { items: entities, total: entities.length })
  );
  await page.route("**/api/v1/completion-models/model-source/migration-validate?*", (route) => {
    const security =
      new URL(route.request().url()).searchParams.get("to_model_id") === "model-security";
    return fulfill(route, {
      compatible: false,
      requires_confirmation: true,
      warning_codes: security
        ? ["security_classification_insufficient:1:Intern"]
        : ["lacks_vision", "kwargs_reset"],
      warnings: security ? ["Lower classification"] : ["Vision", "Settings"]
    });
  });
  await page.route("**/api/v1/completion-models/model-source/migrate", (route) => {
    writes.push(route.request().postDataJSON());
    return fulfill(route, {
      success: true,
      migrated_count: 5,
      failed_count: 0,
      details: {},
      duration: 2.5,
      migration_id: "fixture-migration"
    });
  });
  return { writes };
}

test("model parity: sorts rows, edits token budgets and default, and names provider deletion blockers", async ({
  page
}) => {
  const { writes } = await fixtures(page);
  await page.goto("/admin/models");
  const provider = page.getByRole("region", { name: "Fixture provider", exact: true });
  await expect(
    provider.getByRole("button", { name: "Historical fixture", exact: true })
  ).toHaveCount(0);
  await expect(provider.getByText("3 modeller · nyckel ...fixture", { exact: true })).toBeVisible();
  const table = provider.getByRole("table");
  await table.getByRole("button", { name: /Sortera efter Modell/ }).click();
  await expect(table.getByRole("row").nth(1)).toHaveAttribute("data-model-id", "model-compatible");
  await provider.getByRole("button", { name: "Zeta fixture", exact: true }).click();
  const detail = page.getByRole("dialog", { name: "Zeta fixture", exact: true });
  await expect(detail.getByText("provider/model-source", { exact: true })).toBeVisible();
  await expect(detail.getByText("4 096", { exact: true })).toBeVisible();
  await detail.getByRole("button", { name: "Redigera", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "Redigera modell", exact: true });
  await edit.getByLabel("Max indatatokens", { exact: true }).fill("0");
  await edit.getByRole("button", { name: "Spara", exact: true }).click();
  await expect(edit.getByLabel("Max indatatokens", { exact: true })).toBeFocused();
  await expect(edit.locator("#model-max-input-problem")).toHaveText("Ange ett heltal större än 0.");
  expect(writes).toEqual([]);
  await edit.getByLabel("Max indatatokens", { exact: true }).fill("128000");
  await edit.getByRole("switch", { name: "Ange som standardmodell" }).uncheck();
  await edit.getByRole("button", { name: "Spara", exact: true }).click();
  await expect(edit).not.toBeVisible();
  expect(writes).toEqual([
    expect.objectContaining({
      is_default: false,
      max_input_tokens: 128000,
      max_output_tokens: 4096
    })
  ]);
  await provider
    .getByRole("button", { name: "Fler alternativ för Fixture provider", exact: true })
    .click();
  await page.getByRole("menuitem", { name: /^Ta bort leverantör/ }).click();
  const blocked = page.getByRole("dialog", { name: "Fixture provider kan inte tas bort än" });
  for (const name of ["Alfa fixture", "Zeta fixture", "Historical fixture"])
    await expect(blocked.getByText(name, { exact: true })).toBeVisible();
  await blocked.getByRole("button", { name: "Stäng", exact: true }).click();
  await expect(
    provider.getByRole("button", { name: "Fler alternativ för Fixture provider", exact: true })
  ).toBeFocused();
  await provider.screenshot({ path: test.info().outputPath("models-desktop-light.png") });
});

test("model parity: reviews named impact, separates notes and resets acknowledgement on a security target", async ({
  page
}) => {
  const { writes } = await fixtures(page);
  await page.goto("/admin/models");
  await page.getByRole("button", { name: "Zeta fixture", exact: true }).click();
  await page
    .getByRole("dialog", { name: "Zeta fixture", exact: true })
    .getByRole("button", { name: "Migrera", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Migrera modell", exact: true });
  for (const name of [
    "Upphandling",
    "Protokoll",
    "Ärendesortering",
    "Avtalsgranskning",
    "Mötesmall"
  ])
    await expect(dialog.getByText(name, { exact: true })).toBeVisible();
  await dialog.getByRole("combobox", { name: "Migreringsmål" }).click();
  await page.getByRole("option", { name: "Alfa fixture", exact: true }).click();
  await expect(dialog.getByText("Kompatibilitetsvarningar", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Bra att veta", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Migrera", exact: true }).click();
  const compatibility = dialog.getByRole("checkbox", {
    name: "Fortsätt även om kompatibilitetsvarningar finns"
  });
  await expect(compatibility).toBeFocused();
  expect(writes).toEqual([]);
  await compatibility.check();
  await dialog.getByRole("combobox", { name: "Migreringsmål" }).click();
  await page.getByRole("option", { name: "Public fixture", exact: true }).click();
  const security = dialog.getByRole("checkbox", { name: /vill tvinga igenom den/ });
  await expect(security).not.toBeChecked();
  await dialog.getByRole("button", { name: "Migrera", exact: true }).click();
  await expect(security).toBeFocused();
  expect(writes).toEqual([]);
  await security.check();
  await dialog.screenshot({ path: test.info().outputPath("models-migration-impact.png") });
  await dialog.getByRole("button", { name: "Migrera", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(writes).toEqual([
    { to_model_id: "model-security", confirm_migration: true, force_override: true }
  ]);
});

test.describe("model parity on a touch screen", () => {
  test.use({
    viewport: { width: 320, height: 740 },
    hasTouch: true,
    isMobile: true,
    colorScheme: "dark"
  });
  test("chooses E5 and hosting before adding an embedding model without horizontal page overflow", async ({
    page
  }) => {
    const { writes } = await fixtures(page);
    await page.goto("/admin/models");
    await page
      .getByRole("region", { name: "Fixture provider", exact: true })
      .getByRole("button", { name: "Lägg till modell i Fixture provider", exact: true })
      .click();
    const dialog = page.getByRole("dialog", { name: "Lägg till modell", exact: true });
    await dialog.getByRole("combobox", { name: /^Modelltyp/ }).click();
    await page.getByRole("option", { name: "Inbäddning", exact: true }).click();
    const hosting = dialog.getByRole("combobox", { name: /^Hosting-region/ });
    await expect(hosting).toContainText("USA");
    await hosting.click();
    await page.getByRole("option", { name: "Sverige", exact: true }).click();
    await dialog.getByRole("combobox", { name: /^Modellfamilj/ }).click();
    await page.getByRole("option", { name: "E5 (HuggingFace)", exact: true }).click();
    await dialog.getByRole("checkbox", { name: /multilingual-e5-large/ }).check();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true
    );
    await dialog.screenshot({ path: test.info().outputPath("models-embedding-touch-dark.png") });
    await dialog.getByRole("button", { name: "Lägg till 1 modell", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    expect(writes).toEqual([
      expect.objectContaining({ family: "e5", hosting: "swe", name: "multilingual-e5-large" })
    ]);
  });
});
