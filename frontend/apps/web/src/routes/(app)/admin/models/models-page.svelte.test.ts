import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const api = vi.hoisted(() => ({
  models: {
    list: vi.fn(async () => ({})),
    update: vi.fn(async () => ({}))
  },
  modelProviders: {
    getCapabilities: vi.fn(async () => ({ providers: {}, default_fields: [] })),
    getFavorites: vi.fn(async () => ({ providers: [] })),
    setFavorites: vi.fn(async () => ({}))
  },
  tenantModels: {}
}));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => api }));
vi.mock("$app/navigation", () => ({
  invalidate: vi.fn(async () => {}),
  replaceState: vi.fn(),
  goto: vi.fn(),
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  onNavigate: vi.fn(),
  invalidateAll: vi.fn(),
  preloadData: vi.fn(),
  preloadCode: vi.fn(),
  disableScrollHandling: vi.fn()
}));
import ModelsPage from "./+page.svelte";

const openai = {
  id: "p-openai",
  tenant_id: "t",
  name: "OpenAI",
  provider_type: "openai",
  config: {},
  is_active: true,
  is_managed: false,
  masked_api_key: "...4f2a"
};
// Comes with the installation; Eneo stores its name in English.
const tools = {
  ...openai,
  id: "p-tools",
  name: "Eneo tool service",
  provider_type: "eneo_tool_service",
  is_managed: true,
  masked_api_key: null
};
const timestral = {
  id: "f1",
  name: "default",
  nickname: "Timestral",
  org: "Mistral AI",
  open_source: true,
  is_deprecated: false,
  is_org_enabled: true,
  tenant_id: "t",
  provider_id: "p-tools",
  provider_name: "Eneo tool service",
  provider_type: "eneo_tool_service",
  security_classification: null,
  // The bundled Prognos source, stored with Eneo's English name.
  used_by_mcp_servers: [{ id: "src", name: "Forecast", purpose: "forecast" }]
};

function show(forecastModels: unknown[] = [timestral]) {
  return render(ModelsPage, {
    data: {
      models: {
        completionModels: [
          {
            id: "c1",
            name: "gpt-5",
            nickname: "GPT-5",
            provider_id: "p-openai",
            is_org_enabled: true,
            security_classification: null
          }
        ],
        embeddingModels: [],
        transcriptionModels: [],
        imageModels: [],
        rerankModels: [],
        forecastModels
      },
      providers: [tools, openai],
      favoriteProviders: [],
      securityClassifications: {
        security_enabled: true,
        security_classifications: [{ id: "s3", name: "Klass 3", security_level: 3 }]
      }
    } as never
  });
}

async function openForecastTab() {
  await page.getByRole("tab", { name: m.forecast_models(), exact: true }).click();
  await expect.element(page.getByText("Timestral", { exact: true })).toBeVisible();
}

describe("Admin > Models, forecast models", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists the forecast model under the provider that comes with the installation", async () => {
    show();
    await openForecastTab();
    const tab = page.getByRole("tabpanel");
    // Named in the reader's language, with the glyph's chip and no key, edit,
    // delete or "add model": it has none of them by design.
    await expect.element(tab.getByText(m.mcp_auth_bundled(), { exact: true })).toBeVisible();
    await expect
      .element(tab.getByText(m.provider_included_in_installation(), { exact: true }))
      .toBeVisible();
    expect(tab.getByText("Eneo tool service", { exact: true }).elements()).toHaveLength(0);
    expect(tab.getByTitle(m.edit_provider()).elements()).toHaveLength(0);
    expect(tab.getByRole("button", { name: m.add_model() }).elements()).toHaveLength(0);
    expect(tab.getByRole("button", { name: m.add_provider() }).elements()).toHaveLength(0);
    // No price chip: the model has no price, not an unknown one.
    expect(tab.getByLabelText(`${m.model_cost_unknown()}: –`).elements()).toHaveLength(0);
    // The row's own menu is the only one: the provider has none.
    expect(tab.getByRole("button", { name: m.actions(), exact: true }).elements()).toHaveLength(1);
    // Named after the Function, not the source's stored English name.
    await expect
      .element(tab.getByText(m.model_used_by_function({ function: m.forecast() }), { exact: true }))
      .toBeVisible();
  });

  it("says who made the model in its details, apart from the provider that runs it", async () => {
    show();
    await openForecastTab();
    await page.getByRole("button", { name: "Timestral" }).click();
    const dialog = page.getByRole("dialog");
    await expect.element(dialog.getByText(m.model_developed_by(), { exact: true })).toBeVisible();
    await expect.element(dialog.getByText("Mistral AI", { exact: true })).toBeVisible();
    expect(dialog.getByText(m.provider(), { exact: true }).elements()).toHaveLength(0);
    // It has no price to set, so no price row that calls one unknown.
    expect(dialog.getByText(m.model_pricing_label(), { exact: true }).elements()).toHaveLength(0);
  });

  it("turns the model off, and renames and classifies it, through the forecast endpoint", async () => {
    show();
    await openForecastTab();
    await page.getByRole("switch", { name: `Timestral — ${m.toggle_to_disable_model()}` }).click();
    await vi.waitFor(() =>
      expect(api.models.update).toHaveBeenCalledWith({
        forecastModel: { id: "f1" },
        update: { is_org_enabled: false }
      })
    );

    await page.getByRole("button", { name: m.actions(), exact: true }).click();
    // Nothing to delete or migrate: it comes with the installation.
    expect(page.getByRole("menuitem", { name: m.delete_model() }).elements()).toHaveLength(0);
    expect(page.getByRole("menuitem", { name: m.migrate_model_usage() }).elements()).toHaveLength(
      0
    );
    await page.getByRole("menuitem", { name: m.edit_model() }).click();

    const dialog = page.getByRole("dialog");
    await expect
      .element(dialog.getByRole("textbox", { name: m.model_identifier(), exact: false }))
      .toHaveAttribute("readonly");
    // Eneo sets everything else about it.
    expect(dialog.getByLabelText(m.hosting_region()).elements()).toHaveLength(0);
    expect(dialog.getByLabelText(m.model_description()).elements()).toHaveLength(0);
    expect(dialog.getByLabelText(m.model_label_open_source()).elements()).toHaveLength(0);

    await dialog
      .getByRole("textbox", { name: m.display_name(), exact: true })
      .fill("Prognosmodellen");
    await dialog.getByRole("button", { name: m.security_classification() }).click();
    await page.getByRole("option", { name: "Klass 3" }).click();
    await dialog.getByRole("button", { name: m.save(), exact: true }).click();
    await vi.waitFor(() =>
      expect(api.models.update).toHaveBeenLastCalledWith({
        forecastModel: { id: "f1" },
        update: { display_name: "Prognosmodellen", security_classification: { id: "s3" } }
      })
    );
  });

  it("saves only the class when that is all the admin changed, keeping a rename made meanwhile", async () => {
    const view = show();
    await openForecastTab();
    await page.getByRole("button", { name: m.actions(), exact: true }).click();
    await page.getByRole("menuitem", { name: m.edit_model() }).click();
    const dialog = page.getByRole("dialog");
    await expect.element(dialog).toBeVisible();

    // Another admin renames the model; the refreshed data reaches the open dialog.
    await view.rerender({
      data: {
        models: {
          completionModels: [],
          embeddingModels: [],
          transcriptionModels: [],
          imageModels: [],
          rerankModels: [],
          forecastModels: [{ ...timestral, nickname: "Timestral 28M" }]
        },
        providers: [tools, openai],
        favoriteProviders: [],
        securityClassifications: {
          security_enabled: true,
          security_classifications: [{ id: "s3", name: "Klass 3", security_level: 3 }]
        }
      } as never
    });

    await dialog.getByRole("button", { name: m.security_classification() }).click();
    await page.getByRole("option", { name: "Klass 3" }).click();
    await dialog.getByRole("button", { name: m.save(), exact: true }).click();
    await vi.waitFor(() =>
      expect(api.models.update).toHaveBeenLastCalledWith({
        forecastModel: { id: "f1" },
        update: { security_classification: { id: "s3" } }
      })
    );
  });

  it("says where the forecast model comes from while there is none", async () => {
    show([]);
    await page.getByRole("tab", { name: m.forecast_models(), exact: true }).click();
    await expect
      .element(page.getByText(m.forecast_models_empty_title(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.forecast_models_empty_description(), { exact: true }))
      .toBeVisible();
    // No provider of its own can be added.
    expect(page.getByRole("button", { name: m.add_provider() }).elements()).toHaveLength(0);
  });

  it("offers only the providers an admin added when adding models", async () => {
    show();
    await page.getByRole("button", { name: m.add_provider(), exact: true }).click();
    const wizard = page.getByRole("dialog");
    await expect.element(wizard.getByRole("button", { name: /OpenAI/ })).toBeVisible();
    expect(wizard.getByRole("button", { name: /Eneo tool service/ }).elements()).toHaveLength(0);
  });
});
