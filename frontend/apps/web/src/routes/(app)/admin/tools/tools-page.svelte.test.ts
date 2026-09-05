import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const api = vi.hoisted(() => ({
  mcpServers: {
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
function pageData(items: ReturnType<typeof source>[]) {
  return {
    eneo: api,
    mcpSettings: { items },
    securityClassifications: { security_classifications: [] },
    providers: []
  } as never;
}
function show(items: ReturnType<typeof source>[] = []) {
  return render(ToolsPage, { data: pageData(items) });
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
    expect(page.getByText("Generate image", { exact: true }).elements()).toHaveLength(0);
    const expand = page.getByRole("button", {
      name: `${m.governance_mcp_show_tools()}: Image Studio`
    });
    await expect.element(expand).toHaveAttribute("aria-expanded", "false");
    await expand.click();
    await expect.element(page.getByText("Generate image", { exact: true })).toBeVisible();
    await expect
      .element(page.getByText("Generate an image from a text description.", { exact: true }))
      .toBeVisible();
    expect(page.getByRole("button", { name: m.sync_tools(), exact: true }).elements()).toHaveLength(
      0
    );
    const collapse = page.getByRole("button", {
      name: `${m.governance_mcp_hide_tools()}: Image Studio`
    });
    await expect.element(collapse).toHaveAttribute("aria-expanded", "true");
    await collapse.click();
    expect(page.getByText("Generate image", { exact: true }).elements()).toHaveLength(0);
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
    await page.getByRole("button", { name: m.deactivate(), exact: true }).click();
    await vi.waitFor(() =>
      expect(api.mcpServers.deactivate).toHaveBeenCalledWith({ id: "images" })
    );
  });

  it("opens deletion from the source menu and requires confirmation", async () => {
    show([source()]);
    expect(page.getByRole("button", { name: m.delete(), exact: true }).elements()).toHaveLength(0);
    await page.getByRole("button", { name: `${m.actions()}: Image Studio` }).click();
    await page.getByRole("menuitem", { name: m.delete(), exact: true }).click();
    await expect.element(page.getByRole("dialog")).toBeVisible();
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
    await page.getByRole("button", { name: m.activate(), exact: true }).click();
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
    await page.getByRole("button", { name: m.activate(), exact: true }).click();
    await expect.element(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: m.activate(), exact: true }).click();
    await vi.waitFor(() => expect(api.mcpServers.activate).toHaveBeenCalledTimes(2));
  });

  it("shows group-only setup without pretending there is a default", async () => {
    show([source({ audience: "groups", user_groups: [{ id: "group", name: "Design team" }] })]);
    await expect.element(page.getByText("Design team")).toBeVisible();
    await expect.element(page.getByText(m.tools_group_override())).toBeVisible();
    expect(page.getByText(m.tools_no_default()).elements().length).toBe(2);
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
    await expect
      .element(page.getByRole("button", { name: m.activate(), exact: true }))
      .toBeDisabled();
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
