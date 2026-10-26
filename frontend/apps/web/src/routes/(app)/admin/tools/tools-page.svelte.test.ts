import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { CAPABILITIES } from "$lib/features/mcp/capabilities";

const api = vi.hoisted(() => ({
  mcpServers: {
    createBundled: vi.fn(async () => ({})),
    create: vi.fn(async (_payload: Record<string, unknown>) => ({})),
    update: vi.fn(async () => ({})),
    activate: vi.fn(async () => ({})),
    deactivate: vi.fn(async () => ({})),
    delete: vi.fn(async () => ({})),
    getTools: vi.fn(async () => ({ items: [] }))
  },
  userGroups: { list: vi.fn(async () => []) },
  models: {
    list: vi.fn(async () => ({
      imageModels: [
        {
          id: "model-1",
          name: "gpt-image",
          nickname: "Studio",
          provider_id: "provider-1",
          provider_name: "OpenAI",
          is_org_enabled: true,
          is_deprecated: false,
          default_size: "1024x1024",
          default_quality: "auto"
        }
      ]
    }))
  },
  modelProviders: {
    list: vi.fn(async () => [
      { id: "provider-1", name: "OpenAI", provider_type: "openai", is_active: true }
    ])
  }
}));
const wizardApi = {
  getCapabilities: vi.fn(async () => ({
    providers: { openai: { modes: ["image"], models: { image: [] }, fields: [] } },
    default_fields: []
  })),
  validateModel: vi.fn(async () => ({ success: true })),
  listModels: vi.fn(async () => []),
  getFavorites: vi.fn(async () => [])
};
Object.assign(api.modelProviders, wizardApi);
Object.assign(api, {
  tenantModels: {
    createImage: vi.fn(async () => {
      const model = {
        id: "model-2",
        name: "new-image",
        nickname: "New Studio",
        provider_id: "provider-1",
        provider_name: "OpenAI",
        is_org_enabled: true,
        is_deprecated: false,
        default_size: "1024x1024",
        default_quality: "auto"
      };
      api.models.list.mockResolvedValue({ imageModels: [model] });
      return model;
    })
  }
});
Object.assign(api.mcpServers, {
  approveAllToolChanges: vi.fn(async () => ({})),
  listTools: vi.fn(async () => ({ items: [] }))
});
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
vi.mock("$app/stores", async () => {
  const { writable } = await import("svelte/store");
  return { page: writable({ url: new URL("http://localhost/admin/tools"), state: {} }) };
});
import ToolsPage from "./+page.svelte";

function source(overrides: Record<string, unknown> = {}) {
  return {
    mcp_server_id: "images",
    name: "Image Studio",
    purpose: "image_generation",
    http_auth_type: "internal",
    http_url: "http://localhost/mcp",
    audience: "everyone",
    audience_priority: 100,
    user_groups: [],
    is_enabled: true,
    readiness_reason: null,
    tools: [],
    image_model_id: "model-1",
    image_model: { id: "model-1", name: "gpt-image", nickname: "Studio", provider_name: "OpenAI" },
    ...overrides
  };
}
function pageData(items: ReturnType<typeof source>[], bundled: Record<string, unknown>[] = []) {
  return {
    eneo: api,
    mcpSettings: { items },
    securityClassifications: { security_classifications: [] },
    providers: [],
    bundled: { items: bundled }
  } as never;
}
function show(items: ReturnType<typeof source>[] = []) {
  return render(ToolsPage, { data: pageData(items) });
}

async function activation(name: string, label: string) {
  await page.getByRole("button", { name: `${m.actions()}: ${name}` }).click();
  return page.getByRole("menuitem", { name: label, exact: true });
}
describe("Tools capability configuration", () => {
  beforeEach(() => vi.clearAllMocks());

  it("opens functions by default and keeps both empty capability cards", async () => {
    show();
    await expect
      .element(page.getByRole("heading", { name: m.image_generation(), exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByRole("heading", { name: m.web_search(), exact: true }))
      .toBeVisible();
    await expect
      .element(
        page.getByRole("button", {
          name: m.capability_configure({ capability: m.image_generation().toLocaleLowerCase() })
        })
      )
      .toBeVisible();
  });

  it("offers Charts as a function and adds its bundled provider through Turn on", async () => {
    render(ToolsPage, {
      data: pageData(
        [],
        [{ tool: "charts", purpose: "charts", available: true, mcp_server_id: null }]
      )
    });
    await expect
      .element(page.getByRole("heading", { name: m.charts(), exact: true }))
      .toBeVisible();
    await page.getByRole("button", { name: m.tools_builtin_turn_on(), exact: true }).click();
    expect(api.mcpServers.createBundled).toHaveBeenCalledWith({ tool: "charts", activate: true });
  });

  it("expands and collapses configured tools for a model-backed image source", async () => {
    show([
      source({
        tools: [
          {
            id: "builtin-tool",
            name: "generate_image",
            title: "Generate image",
            description:
              "Generate an image from a text description.\n\nDetailed model instructions.",
            is_enabled_by_default: true,
            input_schema: { type: "object" }
          }
        ]
      })
    ]);
    // A built-in provider's tool is Eneo's own, so the listing shows its
    // localized title and description rather than the synced English strings.
    const title = m.tool_generate_image_title();
    expect(page.getByText(title, { exact: true }).elements()).toHaveLength(0);
    const expand = page.getByRole("button", {
      name: `${m.governance_mcp_show_tools()}: Image Studio`
    });
    await expect.element(expand).toHaveAttribute("aria-expanded", "false");
    await expand.click();
    await expect.element(page.getByText(title, { exact: true })).toBeVisible();
    await expect
      .element(page.getByText(m.tool_generate_image_description(), { exact: true }))
      .toBeVisible();
    expect(page.getByText("Generate image", { exact: true }).elements()).toHaveLength(0);
    expect(page.getByRole("button", { name: m.sync_tools(), exact: true }).elements()).toHaveLength(
      0
    );
    const collapse = page.getByRole("button", {
      name: `${m.governance_mcp_hide_tools()}: Image Studio`
    });
    await expect.element(collapse).toHaveAttribute("aria-expanded", "true");
    await collapse.click();
    expect(page.getByText(title, { exact: true }).elements()).toHaveLength(0);
  });

  it("configures a model and submits save-and-activate together", async () => {
    show();
    await page
      .getByRole("button", {
        name: m.capability_configure({ capability: m.image_generation().toLocaleLowerCase() })
      })
      .click();
    await page
      .getByRole("combobox", { name: m.mcp_builtin_image_model(), exact: false })
      .selectOptions("model-1");
    await page.getByRole("textbox", { name: m.name(), exact: false }).fill("Image Studio");
    await page.getByRole("button", { name: m.tools_save_activate(), exact: true }).click();
    await vi.waitFor(() =>
      expect(api.mcpServers.create).toHaveBeenCalledWith(
        expect.objectContaining({
          purpose: "image_generation",
          http_auth_type: "internal",
          image_model_id: "model-1",
          activate: true
        })
      )
    );
  });

  it("saves a built-in source after an http URL with a user name was typed for an external one", async () => {
    // Kills: the https hint judging the URL a built-in provider never submits,
    // which kept Save disabled with no visible reason.
    show();
    await page
      .getByRole("button", {
        name: m.capability_configure({ capability: m.image_generation().toLocaleLowerCase() })
      })
      .click();
    const source = page.getByLabelText(m.mcp_source_label(), { exact: true });
    await source.click();
    await page.getByRole("option", { name: m.mcp_source_external(), exact: true }).click();
    await page
      .getByRole("textbox", { name: m.server_url_required(), exact: false })
      .fill("http://user:secret@example.test/mcp");
    await source.click();
    await page.getByRole("option", { name: m.mcp_source_builtin(), exact: true }).click();
    await page
      .getByRole("combobox", { name: m.mcp_builtin_image_model(), exact: false })
      .selectOptions("model-1");
    await page.getByRole("textbox", { name: m.name(), exact: false }).fill("Image Studio");
    await page.getByRole("button", { name: m.tools_save_activate(), exact: true }).click();
    await vi.waitFor(() =>
      expect(api.mcpServers.create).toHaveBeenCalledWith(
        expect.objectContaining({ http_auth_type: "internal", image_model_id: "model-1" })
      )
    );
  });

  it("names the model a Prognos source runs and where, and why it is blocked while it is off", async () => {
    const forecast = (readiness: string | null) =>
      source({
        mcp_server_id: "forecast",
        name: "Forecast",
        purpose: "forecast",
        http_auth_type: "bundled",
        http_url: "http://runtime:8765/forecast",
        image_model_id: null,
        image_model: null,
        readiness_reason: readiness,
        forecast_model_id: "f1",
        // The stored provider name; the line says where it runs in the reader's language.
        forecast_model: {
          id: "f1",
          name: "default",
          nickname: "Timestral",
          provider_name: "Eneo tool service",
          is_enabled: readiness === null
        }
      });
    const offer = [
      { tool: "forecast", purpose: "forecast", available: true, mcp_server_id: "forecast" }
    ];
    const rendered = render(ToolsPage, { data: pageData([forecast(null)], offer) });
    await expect
      .element(page.getByRole("heading", { level: 3, name: m.forecast(), exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.tools_builtin_forecast_summary(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(`${m.model()} · Timestral · ${m.mcp_auth_bundled()}`))
      .toBeVisible();
    // The name opens Admin > Models on the forecast models, where it is governed.
    await expect
      .element(page.getByRole("link", { name: "Timestral", exact: true }))
      .toHaveAttribute("href", "/admin/models?tab=forecast_models");
    expect(page.getByText(m.tools_readiness_model_disabled()).elements()).toHaveLength(0);

    // Switched off under Admin > Models: the source says why, like an image source.
    await rendered.rerender({ data: pageData([forecast("model_disabled")], offer) });
    await expect.element(page.getByText(m.tools_readiness_model_disabled())).toBeVisible();
  });

  it("links an image source's model to the image models under Admin > Models", async () => {
    show([source()]);
    await expect
      .element(page.getByRole("link", { name: "Studio", exact: true }))
      .toHaveAttribute("href", "/admin/models?tab=image_models");
  });

  it("keeps a Prognos source following its model's class unless an edit changes the class", async () => {
    const own = { id: "s2", name: "Klass 2", security_level: 2 };
    const inherited = { id: "s3", name: "Klass 3", security_level: 3 };
    const forecast = source({
      mcp_server_id: "forecast",
      name: "Forecast",
      purpose: "forecast",
      http_auth_type: "bundled",
      http_url: "http://runtime:8765/forecast",
      image_model_id: null,
      image_model: null,
      forecast_model_id: "f1",
      forecast_model: {
        id: "f1",
        name: "default",
        nickname: "Timestral",
        provider_name: "Eneo tool service",
        is_enabled: true
      },
      // No class of its own: the API reports the forecast model's.
      security_classification: inherited
    });
    const offer = [
      { tool: "forecast", purpose: "forecast", available: true, mcp_server_id: "forecast" }
    ];
    render(ToolsPage, {
      data: {
        ...(pageData([forecast], offer) as object),
        securityClassifications: { security_classifications: [inherited, own] }
      } as never
    });
    const edit = async () => {
      await page.getByRole("button", { name: `${m.actions()}: ${m.forecast()}` }).click();
      await page.getByRole("menuitem", { name: m.tools_change(), exact: true }).click();
    };
    const lastUpdate = () =>
      (api.mcpServers.update.mock.lastCall as unknown[] | undefined)?.[0] as Record<
        string,
        unknown
      >;

    // Only the name: the class is left out, so a later class on the model still applies.
    await edit();
    await page.getByRole("textbox", { name: m.name(), exact: false }).fill("Prognos för ekonomi");
    await page.getByRole("button", { name: m.save(), exact: true }).click();
    await vi.waitFor(() =>
      expect(lastUpdate()).toMatchObject({ id: "forecast", name: "Prognos för ekonomi" })
    );
    expect("security_classification" in lastUpdate()).toBe(false);

    // A class the admin chooses becomes the source's own.
    await edit();
    await page.getByRole("button", { name: m.security_classification() }).click();
    await page.getByRole("option", { name: "Klass 2" }).click();
    await page.getByRole("button", { name: m.save(), exact: true }).click();
    await vi.waitFor(() =>
      expect(lastUpdate()).toMatchObject({ security_classification: { id: "s2" } })
    );
  });

  it("keeps an edit action and allows disabling a blocked active source", async () => {
    show([source({ readiness_reason: "model_disabled" })]);
    await expect
      .element(page.getByText(m.tools_readiness_model_disabled(), { exact: false }))
      .toBeVisible();
    await page.getByRole("button", { name: `${m.actions()}: Image Studio` }).click();
    await expect
      .element(page.getByRole("menuitem", { name: m.tools_change(), exact: true }))
      .toBeVisible();
    await page.getByRole("menuitem", { name: m.tools_change(), exact: true }).click();
    await expect.element(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("button", { name: m.cancel(), exact: true }).click();
    await (await activation("Image Studio", m.deactivate())).click();
    await vi.waitFor(() =>
      expect(api.mcpServers.deactivate).toHaveBeenCalledWith({ id: "images" })
    );
  });

  it("opens deletion from the source menu and requires confirmation", async () => {
    show([source()]);
    expect(page.getByRole("button", { name: m.delete(), exact: true }).elements()).toHaveLength(0);
    await page.getByRole("button", { name: `${m.actions()}: Image Studio` }).click();
    await page.getByRole("menuitem", { name: m.delete(), exact: true }).click();
    await expect.element(page.getByRole("alertdialog")).toBeVisible();
    expect(api.mcpServers.delete).not.toHaveBeenCalled();
    await page.getByRole("button", { name: m.delete(), exact: true }).click();
    await vi.waitFor(() => expect(api.mcpServers.delete).toHaveBeenCalledWith({ id: "images" }));
  });

  it("activates a saved source without moving either source after refresh", async () => {
    const rendered = show([
      source(),
      source({ mcp_server_id: "replacement", name: "Replacement", is_enabled: false })
    ]);
    const sourceNames = () =>
      page
        .getByRole("heading", { level: 3 })
        .elements()
        .map((el) => el.textContent);
    expect(sourceNames()).toEqual(["Image Studio", "Replacement"]);
    await expect
      .element(page.getByText(m.tools_replace_default({ name: "Image Studio" })))
      .toBeVisible();
    await (await activation("Replacement", m.activate())).click();
    await vi.waitFor(() =>
      expect(api.mcpServers.activate).toHaveBeenCalledWith({ id: "replacement" })
    );
    await rendered.rerender({
      data: pageData([
        source({ is_enabled: false }),
        source({ mcp_server_id: "replacement", name: "Replacement", is_enabled: true })
      ])
    });
    await expect
      .element(page.getByText(m.tools_replace_default({ name: "Replacement" })))
      .toBeVisible();
    expect(sourceNames()).toEqual(["Image Studio", "Replacement"]);
  });

  it("keeps failed activation visible with a retry", async () => {
    api.mcpServers.activate.mockRejectedValueOnce(new Error("Connection unavailable"));
    show([source({ is_enabled: false })]);
    await (await activation("Image Studio", m.activate())).click();
    await expect.element(page.getByRole("alert")).toBeVisible();
    await (await activation("Image Studio", m.activate())).click();
    await vi.waitFor(() => expect(api.mcpServers.activate).toHaveBeenCalledTimes(2));
  });

  it("shows group-only setup without pretending there is a default", async () => {
    show([source({ audience: "groups", user_groups: [{ id: "group", name: "Design team" }] })]);
    await expect.element(page.getByText("Design team")).toBeVisible();
    await expect.element(page.getByText(m.tools_group_override())).toBeVisible();
    // No capability card has a default provider: group-only setup does not count as one.
    expect(page.getByText(m.tools_no_default()).elements().length).toBe(CAPABILITIES.length);
  });

  it("hides function connections by default and reveals only external ones on request", async () => {
    show([
      source(),
      source({
        mcp_server_id: "remote",
        name: "Remote Images",
        http_auth_type: "none",
        http_url: "https://example.test/mcp"
      }),
      source({
        mcp_server_id: "general",
        name: "General Tools",
        purpose: "general",
        http_auth_type: "none"
      })
    ]);
    await page.getByRole("tab", { name: m.mcp_servers(), exact: true }).click();
    await expect
      .element(page.getByRole("table").getByText("General Tools", { exact: true }))
      .toBeVisible();
    expect(
      page.getByRole("table").getByText("Remote Images", { exact: true }).elements()
    ).toHaveLength(0);
    await page.getByRole("switch", { name: m.tools_show_function_servers() }).click();
    await expect
      .element(page.getByRole("table").getByText("Remote Images", { exact: true }))
      .toBeVisible();
    expect(
      page.getByRole("table").getByText("Image Studio", { exact: true }).elements()
    ).toHaveLength(0);
    await page.getByRole("switch", { name: m.tools_show_function_servers() }).click();
    expect(
      page.getByRole("table").getByText("Remote Images", { exact: true }).elements()
    ).toHaveLength(0);
    await expect
      .element(page.getByRole("table").getByText("General Tools", { exact: true }))
      .toBeVisible();
  });
  it("returns from adding an image model with the new model selected", async () => {
    show();
    await page
      .getByRole("button", {
        name: m.capability_configure({ capability: m.image_generation().toLocaleLowerCase() })
      })
      .click();
    await page.getByRole("button", { name: m.tools_add_image_model() }).click();
    await page.getByRole("button", { name: /OpenAI/ }).click();
    await page.getByRole("textbox", { name: m.model_identifier(), exact: false }).fill("new-image");
    await page.getByRole("textbox", { name: m.display_name(), exact: true }).fill("New Studio");
    await page.getByRole("button", { name: m.finish(), exact: true }).click();
    await expect
      .element(page.getByRole("combobox", { name: m.mcp_builtin_image_model(), exact: false }))
      .toHaveValue("model-2");
    await page.getByRole("textbox", { name: m.name(), exact: false }).fill("New source");
    await page.getByRole("button", { name: m.tools_save_activate(), exact: true }).click();
    await vi.waitFor(() =>
      expect(api.mcpServers.create).toHaveBeenCalledWith(
        expect.objectContaining({ image_model_id: "model-2", activate: true })
      )
    );
    await expect.poll(() => document.body.style.pointerEvents).not.toBe("none");
  });

  it("returns to configuration when the model wizard is dismissed with Escape", async () => {
    show();
    await page
      .getByRole("button", {
        name: m.capability_configure({ capability: m.image_generation().toLocaleLowerCase() })
      })
      .click();
    await page.getByRole("button", { name: m.tools_add_image_model() }).click();
    await expect.element(page.getByRole("button", { name: /OpenAI/ })).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await expect
      .element(page.getByRole("combobox", { name: m.mcp_builtin_image_model(), exact: false }))
      .toBeVisible();
    expect(api.mcpServers.create).not.toHaveBeenCalled();
  });

  it("keeps an invalid persisted model visible when editing", async () => {
    show([
      source({
        image_model_id: "deleted",
        image_model: { id: "deleted", name: "Deleted model" },
        readiness_reason: "model_missing"
      })
    ]);
    await page.getByRole("button", { name: `${m.actions()}: Image Studio` }).click();
    await page.getByRole("menuitem", { name: m.tools_change(), exact: true }).click();
    await expect
      .element(page.getByRole("combobox", { name: m.mcp_builtin_image_model(), exact: false }))
      .toHaveValue("deleted");
    await expect.element(page.getByRole("option", { name: "Deleted model" })).toBeInTheDocument();
  });

  it("starts web-search setup with an external connection and saves it inactive", async () => {
    show();
    await page
      .getByRole("button", {
        name: m.capability_configure({ capability: m.web_search().toLocaleLowerCase() })
      })
      .click();
    expect(
      page.getByRole("combobox", { name: m.mcp_builtin_image_model(), exact: false }).elements()
    ).toHaveLength(0);
    await page.getByRole("textbox", { name: m.name(), exact: false }).fill("Search service");
    await page
      .getByRole("textbox", { name: m.server_url_required(), exact: false })
      .fill("https://search.example/mcp");
    await page.getByRole("button", { name: m.save(), exact: true }).click();
    await vi.waitFor(() =>
      expect(api.mcpServers.create).toHaveBeenCalledWith(
        expect.objectContaining({ purpose: "web_search", http_auth_type: "none" })
      )
    );
    expect(api.mcpServers.create.mock.calls[0][0]).not.toHaveProperty("activate", true);
    await expect.element(page.getByRole("status")).toHaveTextContent(m.tools_saved_inactive());
  });

  it("exposes tool approval before an external source can be activated", async () => {
    show([
      source({
        http_auth_type: "none",
        is_enabled: false,
        readiness_reason: "no_approved_tools",
        tools: [
          {
            id: "tool-1",
            name: "generate",
            requires_approval: true,
            pending_description: "Generate",
            pending_input_schema: { type: "object" },
            description: null,
            input_schema: null,
            is_enabled: true,
            is_enabled_by_default: true,
            removed_from_remote: false
          }
        ]
      })
    ]);
    await expect.element(await activation("Image Studio", m.activate())).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    await page
      .getByRole("button", { name: `${m.governance_mcp_show_tools()}: Image Studio` })
      .click();
    await page.getByRole("button", { name: m.approve_all(), exact: true }).click();
    await vi.waitFor(() =>
      expect(
        (api.mcpServers as unknown as { listTools: ReturnType<typeof vi.fn> }).listTools
      ).toHaveBeenCalledWith({ mcp_server_id: "images" })
    );
  });
});
