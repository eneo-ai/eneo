// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { SECURITY_CLASSIFICATIONS_KEY } from "@/features/admin/security-classifications/security-classifications";
import { expectNoAxeViolations } from "@/test/axe";
import { CAPABILITIES_KEY, PROVIDERS_KEY } from "./model-providers";
import { MODELS_KEY, type ModelsPresentation } from "./models";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("sonner", () => ({ toast }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/components/providers/app-context", () => ({
  useAppContext: () => ({ tenant: { show_model_pricing: true } })
}));

import { ModelsPage } from "./models-page";

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });

const completion = (overrides: Record<string, unknown>) => ({
  id: "c1",
  name: "claude-opus-4-7",
  nickname: "Claude Opus 4.7",
  max_input_tokens: 200000,
  max_output_tokens: 32000,
  is_deprecated: false,
  vision: true,
  reasoning: true,
  supports_tool_calling: true,
  input_cost_per_token: "0.000005",
  output_cost_per_token: "0.000025",
  is_org_enabled: true,
  is_org_default: true,
  provider_id: "p-anthropic",
  security_classification: { id: "s3", name: "Klass 3", security_level: 3 },
  token_limit: 200000,
  supported_model_kwargs: {},
  ...overrides
});

const presentation = {
  completion_models: [
    completion({}),
    completion({
      id: "c2",
      name: "claude-3-7-sonnet-20250219",
      nickname: "Claude 3.7 Sonnet",
      vision: true,
      reasoning: false,
      supports_tool_calling: false,
      is_org_default: false,
      deprecation_date: "2020-01-01",
      security_classification: null
    })
  ],
  embedding_models: [
    {
      id: "e1",
      name: "intfloat/multilingual-e5-large",
      nickname: "Multilingual E5 Large",
      is_deprecated: false,
      open_source: true,
      is_org_enabled: false,
      provider_id: "p-vllm",
      security_classification: { id: "s3", name: "Klass 3", security_level: 3 }
    }
  ],
  transcription_models: []
} as unknown as ModelsPresentation;

const provider = (id: string, name: string, type: string, key: string | null) => ({
  id,
  tenant_id: "t",
  name,
  provider_type: type,
  config: {},
  is_active: true,
  masked_api_key: key,
  key_expires_on: null,
  connection_check: null,
  connection_check_supported: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z"
});

const providers = [
  provider("p-anthropic", "Anthropic", "anthropic", "...4f2a"),
  // Self-hosted: no key needed.
  provider("p-vllm", "vLLM", "hosted_vllm", null),
  // Needs a key but has none (and no models yet).
  provider("p-openai", "OpenAI", "openai", null)
];

/** vLLM's key is optional; every other type needs one (the backend's defaults). */
const capabilities = {
  providers: {
    hosted_vllm: {
      modes: ["completion", "embedding"],
      models: {},
      fields: [{ name: "api_key", required: false, secret: true, in: "credentials" }]
    }
  },
  default_fields: [{ name: "api_key", required: true, secret: true, in: "credentials" }]
};

const security = {
  security_enabled: true,
  security_classifications: [{ id: "s3", name: "Klass 3", security_level: 3 }]
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/** Opens a row's (or a card's) menu from the keyboard; returns the menu it controls. */
function openRowMenu(name: string, prefix = "Fler åtgärder för") {
  const trigger = screen.getByRole("button", { name: `${prefix} ${name}` });
  trigger.focus();
  // jsdom does not turn Enter into a click; Astryx opens menus on the key.
  fireEvent.keyDown(trigger, { key: "Enter" });
  // jsdom has no popover styles, so every row's (closed) menu is "visible".
  return document.getElementById(trigger.getAttribute("aria-controls")!)!;
}

/** Picks a radio item in a submenu of a row menu. */
function choose(menu: HTMLElement, submenu: string, option: string) {
  fireEvent.keyDown(within(menu).getByRole("menuitem", { name: submenu }), { key: "ArrowRight" });
  const items = within(menu).getByRole("menu", { name: submenu });
  fireEvent.click(within(items).getByRole("menuitemradio", { name: option }));
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } }
  });
  client.setQueryData(MODELS_KEY, presentation);
  client.setQueryData(PROVIDERS_KEY, providers);
  client.setQueryData(CAPABILITIES_KEY, capabilities);
  client.setQueryData(SECURITY_CLASSIFICATIONS_KEY, security);
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/ai-models/") return ok(presentation);
    if (path.endsWith("/migration-history")) return ok([]);
    return ok({});
  });
  api.POST.mockImplementation(() => ok({}));
  render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <QueryClientProvider client={client}>
        <ModelsPage />
      </QueryClientProvider>
    </NextIntlClientProvider>
  );
}

describe("ModelsPage", () => {
  it("shows the header, the tabs and one section per provider", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Modeller" })).toBeTruthy();
    const trail = screen.getByRole("navigation");
    expect(within(trail).getByRole("link", { name: "Administration" })).toBeTruthy();
    // "Konfiguration" is the menu section, not this page.
    expect(within(trail).getByText("Konfiguration").closest("[aria-current]")).toBeNull();
    expect(screen.getByRole("button", { name: "Lägg till leverantör" })).toBeTruthy();

    // The smoke e2e looks this tab up by role and name.
    expect(screen.getByRole("tab", { name: "Migreringshistorik" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Modeller" }).getAttribute("aria-selected")).toBe(
      "true"
    );

    const anthropic = screen.getByRole("region", { name: "Anthropic" });
    expect(within(anthropic).getByText("2 modeller · nyckel ...4f2a")).toBeTruthy();
    expect(within(anthropic).getByText("Inte testad")).toBeTruthy();
    expect(
      within(anthropic).getByRole("button", { name: "Testa anslutning till Anthropic" })
    ).toBeTruthy();
    expect(within(anthropic).getByText("claude-opus-4-7")).toBeTruthy();
    expect(within(anthropic).getByText("Standard")).toBeTruthy();
    expect(within(anthropic).getByText("Utfasad")).toBeTruthy();
    // The badge; the row menu also lists the class as a (hidden) radio item.
    expect(within(anthropic).getByTitle("Klass 3")).toBeTruthy();
    // Prices: visible "$5.00 / $25.00", spelled out for screen readers.
    expect(within(anthropic).getAllByText("Indata $5.00, utdata $25.00")).toHaveLength(2);

    // A self-hosted provider without a key is fine.
    const vllm = screen.getByRole("region", { name: "vLLM" });
    expect(within(vllm).queryByText("Nyckel saknas")).toBeNull();
    expect(within(vllm).getByText("Inte testad")).toBeTruthy();
    // OpenAI has no models yet: listed all the same, so it can get some or go.
    const openai = screen.getByRole("region", { name: "OpenAI" });
    expect(within(openai).getByText("Leverantören har inga modeller än.")).toBeTruthy();
    expect(within(openai).queryByRole("table")).toBeNull();

    await expectNoAxeViolations(document.body);
  });

  it("warns once about the missing key and the deprecated model that is still active", () => {
    renderPage();
    const banner = screen
      .getByText("Några modeller behöver åtgärdas")
      .closest(".astryx-banner-frame");
    expect(banner).toBeTruthy();
    expect(banner?.textContent).toContain("En utfasad modell är fortfarande aktiv");
    expect(banner?.textContent).toContain("Claude 3.7 Sonnet");
    // The provider in its card's words (OpenAI has no models, so no link).
    const row = within(banner as HTMLElement).getByRole("listitem");
    expect(row.textContent).toBe("OpenAINyckel saknas");
  });

  it("filters by type with counts and announces the result", async () => {
    renderPage();
    const types = screen.getByRole("radiogroup", { name: "Modelltyp" });
    expect(within(types).getByRole("radio", { name: "Alla (3)" })).toBeTruthy();
    expect(within(types).getByRole("radio", { name: "Chatt (2)" })).toBeTruthy();

    fireEvent.click(within(types).getByRole("radio", { name: "Inbäddning (1)" }));

    expect(screen.queryByRole("region", { name: "Anthropic" })).toBeNull();
    const vllm = screen.getByRole("region", { name: "vLLM" });
    expect(within(vllm).getByText("Multilingual E5 Large")).toBeTruthy();
    // The type column is dropped while one type is shown.
    expect(within(vllm).queryByRole("columnheader", { name: "Typ" })).toBeNull();
    // Through Astryx's persistent polite live region (WCAG 4.1.3).
    await waitFor(() =>
      expect(document.querySelector("[data-astryx-live-region='polite']")?.textContent).toBe(
        "1 modell visas"
      )
    );
  });

  it("searches model names, technical ids and provider names", () => {
    renderPage();
    const search = screen.getByRole("textbox", { name: "Sök modeller och leverantörer" });

    fireEvent.change(search, { target: { value: "sonnet" } });
    const anthropic = screen.getByRole("region", { name: "Anthropic" });
    expect(within(anthropic).getByText("Claude 3.7 Sonnet")).toBeTruthy();
    expect(within(anthropic).queryByText("Claude Opus 4.7")).toBeNull();

    fireEvent.change(search, { target: { value: "e5-large" } });
    expect(screen.getByRole("region", { name: "vLLM" })).toBeTruthy();

    fireEvent.change(search, { target: { value: "finns inte" } });
    expect(
      screen.getByRole("heading", { name: "Inga leverantörer matchar sökningen" })
    ).toBeTruthy();
  });

  it("enables and disables a model with its switch", async () => {
    renderPage();
    const toggle = screen.getByRole("switch", { name: "Aktivera Multilingual E5 Large" });
    expect((toggle as HTMLInputElement).checked).toBe(false);

    fireEvent.click(toggle);

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/embedding-models/{id}/", {
        params: { path: { id: "e1" } },
        body: { is_org_enabled: true, security_classification: undefined }
      })
    );
  });

  it("moves between tabs with the arrow keys and opens them with Enter", async () => {
    renderPage();
    const models = screen.getByRole("tab", { name: "Modeller" });
    const history = screen.getByRole("tab", { name: "Migreringshistorik" });
    // Roving tabindex: the tab strip is one tab stop.
    expect(models.tabIndex).toBe(0);
    expect(history.tabIndex).toBe(-1);

    models.focus();
    fireEvent.keyDown(models, { key: "ArrowRight" });
    expect(document.activeElement).toBe(history);
    fireEvent.keyDown(history, { key: "Enter" });
    fireEvent.click(history);

    expect(history.getAttribute("aria-selected")).toBe("true");
    const panel = screen.getByRole("tabpanel");
    expect(panel.getAttribute("aria-labelledby")).toBe(history.id);
    expect(history.getAttribute("aria-controls")).toBe(panel.id);
    expect(await within(panel).findByText("Inga migreringar utförda ännu")).toBeTruthy();

    // Back and forth: the model filters are kept while another tab is open.
    fireEvent.click(screen.getByRole("tab", { name: "Modeller" }));
    const types = screen.getByRole("radiogroup", { name: "Modelltyp" });
    fireEvent.click(within(types).getByRole("radio", { name: "Chatt (2)" }));
    fireEvent.click(history);
    fireEvent.click(screen.getByRole("tab", { name: "Modeller" }));
    expect(
      within(screen.getByRole("radiogroup", { name: "Modelltyp" }))
        .getByRole("radio", { name: "Chatt (2)" })
        .getAttribute("aria-checked")
    ).toBe("true");

    fireEvent.click(screen.getByRole("tab", { name: "Inställningar" }));
    const pricing = screen.getByRole("switch", { name: "Visa modellpriser för användare" });
    expect((pricing as HTMLInputElement).checked).toBe(true);
    await act(async () => {
      await expectNoAxeViolations(document.body);
    });
  });

  it("removes an embedding model's security class: Ingen is sent as null", async () => {
    renderPage();
    const menu = openRowMenu("Multilingual E5 Large");
    choose(menu, "Säkerhetsklassificering", "Ingen");

    // Omitting the field would keep the old class on the backend.
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/embedding-models/{id}/", {
        params: { path: { id: "e1" } },
        body: { is_org_enabled: undefined, security_classification: null }
      })
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Multilingual E5 Large har inte längre någon säkerhetsklass."
      )
    );
  });

  it("confirms a new default model and a new security class", async () => {
    renderPage();
    const menu = openRowMenu("Claude 3.7 Sonnet");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Ange som standardmodell" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/completion-models/{id}/", {
        params: { path: { id: "c2" } },
        body: { is_org_default: true }
      })
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Claude 3.7 Sonnet är nu standardmodell.")
    );

    choose(openRowMenu("Claude 3.7 Sonnet"), "Säkerhetsklassificering", "Klass 3");
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Claude 3.7 Sonnet har nu säkerhetsklassen Klass 3."
      )
    );
  });

  it("queues a second press on a switch and keeps it while another write runs", async () => {
    renderPage();
    const writes: Array<() => void> = [];
    api.POST.mockImplementation(
      () =>
        new Promise((resolve) =>
          writes.push(() => resolve({ data: {}, response: new Response("{}") }))
        )
    );
    const toggle = screen.getByRole("switch", { name: "Aktivera Multilingual E5 Large" });

    fireEvent.click(toggle);
    await waitFor(() => expect((toggle as HTMLInputElement).checked).toBe(true));
    // A classification change on the same row must not reset the switch.
    choose(openRowMenu("Multilingual E5 Large"), "Säkerhetsklassificering", "Ingen");
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
    expect((toggle as HTMLInputElement).checked).toBe(true);

    // Pressed again while the first write runs: shown at once, sent after it.
    fireEvent.click(toggle);
    await waitFor(() => expect((toggle as HTMLInputElement).checked).toBe(false));
    expect(api.POST).toHaveBeenCalledTimes(2);
    await act(async () => writes[0]!());
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(3));
    expect(api.POST).toHaveBeenLastCalledWith("/api/v1/embedding-models/{id}/", {
      params: { path: { id: "e1" } },
      body: { is_org_enabled: false, security_classification: undefined }
    });
    await act(async () => writes.forEach((write) => write()));
  });

  it("deletes a model after confirmation and keeps focus on the page", async () => {
    renderPage();
    api.DELETE.mockImplementation(() => ok({}));
    const trigger = screen.getByRole("button", { name: "Fler åtgärder för Claude 3.7 Sonnet" });
    const menu = openRowMenu("Claude 3.7 Sonnet");
    // The list without the model, once it has been deleted.
    api.GET.mockImplementation((path: string) =>
      path === "/api/v1/ai-models/"
        ? ok({ ...presentation, completion_models: presentation.completion_models.slice(0, 1) })
        : ok([])
    );
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Ta bort" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort modell" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(api.DELETE).toHaveBeenCalledWith(
        "/api/v1/admin/tenant-models/completion/{model_id}/",
        {
          params: { path: { model_id: "c2" } }
        }
      )
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Modellen togs bort"));
    await waitFor(() => expect(screen.queryByText("Claude 3.7 Sonnet")).toBeNull());
    expect(trigger.isConnected).toBe(false);
    // The focused row is gone: focus moves to the tab panel, not <body>.
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tabpanel")), {
      timeout: 1500
    });
  });

  it("deletes a provider without models after confirmation and keeps focus on the page", async () => {
    renderPage();
    api.DELETE.mockImplementation(() => ok({}));
    const menu = openRowMenu("OpenAI", "Fler alternativ för");
    // The providers without OpenAI, once it has been deleted.
    api.GET.mockImplementation((path: string) =>
      path === "/api/v1/admin/model-providers/"
        ? ok(providers.filter((item) => item.id !== "p-openai"))
        : path === "/api/v1/ai-models/"
          ? ok(presentation)
          : ok([])
    );
    fireEvent.click(within(menu).getByRole("menuitem", { name: /^Ta bort leverantör/ }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort leverantör" });
    expect(within(dialog).getByText(/Är du säker på att du vill ta bort OpenAI\?/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(api.DELETE).toHaveBeenCalledWith("/api/v1/admin/model-providers/{provider_id}/", {
        params: { path: { provider_id: "p-openai" } }
      })
    );
    await waitFor(() => expect(screen.queryByRole("region", { name: "OpenAI" })).toBeNull());
    expect(toast.success).toHaveBeenCalledWith("OpenAI togs bort");
    // The card and its menu are gone: focus moves to the tab panel, not <body>.
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tabpanel")), {
      timeout: 1500
    });
  });

  it("says at the delete action, and when it is chosen, why a provider with models stays", async () => {
    renderPage();
    const menu = openRowMenu("Anthropic", "Fler alternativ för");
    const remove = within(menu).getByRole("menuitem", { name: /^Ta bort leverantör/ });
    // Reachable like any item, with its reason as text (not a dimmed item).
    expect(remove.getAttribute("aria-disabled")).toBeNull();
    expect(remove.textContent).toContain("Ta bort dess 2 modeller först");

    fireEvent.click(remove);

    const dialog = await screen.findByRole("dialog", {
      name: "Anthropic kan inte tas bort än",
      description:
        "Leverantören har 2 modeller. Ta bort dem i leverantörens tabell först, och ta sedan bort leverantören."
    });
    expect(within(dialog).queryByRole("button", { name: "Ta bort" })).toBeNull();
    await expectNoAxeViolations(document.body);

    fireEvent.click(within(dialog).getByRole("button", { name: "Stäng" }));
    await waitFor(() => expect(dialog.hasAttribute("open")).toBe(false));
    expect(api.DELETE).not.toHaveBeenCalled();
  });

  it("opens a row menu from the keyboard and returns focus to it on Escape", async () => {
    renderPage();
    const trigger = screen.getByRole("button", { name: "Fler åtgärder för Claude Opus 4.7" });
    trigger.focus();
    // jsdom does not turn Enter into a click; Astryx opens menus on the key.
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    // jsdom has no popover styles, so every row's (closed) menu is "visible":
    // take the one this trigger controls.
    const menu = document.getElementById(trigger.getAttribute("aria-controls")!)!;
    expect(menu.getAttribute("role")).toBe("menu");
    for (const name of ["Modelldetaljer", "Redigera", "Migrera", "Ta bort"]) {
      expect(within(menu).getByRole("menuitem", { name })).toBeTruthy();
    }
    // The default model can't be made default again.
    expect(
      within(menu)
        .getByRole("menuitem", { name: "Ange som standardmodell" })
        .getAttribute("aria-disabled")
    ).toBe("true");

    fireEvent.keyDown(document.activeElement ?? menu, { key: "Escape" });
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });
});
