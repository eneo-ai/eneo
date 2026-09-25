// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { SECURITY_CLASSIFICATIONS_KEY } from "@/features/admin/security-classifications/security-classifications";
import { expectNoAxeViolations } from "@/test/axe";
import { PROVIDERS_KEY } from "./model-providers";
import { MODELS_KEY, type ModelsPresentation } from "./models";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
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
      security_classification: null
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

const security = {
  security_enabled: true,
  security_classifications: [{ id: "s3", name: "Klass 3", security_level: 3 }]
};

beforeAll(() => {
  // jsdom has neither; Astryx reads both (layout observers, adaptive menus).
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {}
  }));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } }
  });
  client.setQueryData(MODELS_KEY, presentation);
  client.setQueryData(PROVIDERS_KEY, providers);
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
  it("shows the header, the tabs and one section per provider with models", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Modeller" })).toBeTruthy();
    const trail = screen.getByRole("navigation");
    expect(within(trail).getByRole("link", { name: "Administration" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Lägg till leverantör" })).toBeTruthy();

    // The smoke e2e looks this tab up by role and name.
    expect(screen.getByRole("tab", { name: "Migreringshistorik" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Modeller" }).getAttribute("aria-selected")).toBe(
      "true"
    );

    const anthropic = screen.getByRole("region", { name: "Anthropic" });
    expect(within(anthropic).getByText("2 modeller · nyckel ...4f2a")).toBeTruthy();
    expect(within(anthropic).getByText("Konfigurerad")).toBeTruthy();
    expect(within(anthropic).getByText("claude-opus-4-7")).toBeTruthy();
    expect(within(anthropic).getByText("Standard")).toBeTruthy();
    expect(within(anthropic).getByText("Utfasad")).toBeTruthy();
    // The badge; the row menu also lists the class as a (hidden) radio item.
    expect(within(anthropic).getByTitle("Klass 3")).toBeTruthy();
    // Prices: visible "$5.00 / $25.00", spelled out for screen readers.
    expect(within(anthropic).getAllByText("Indata $5.00, utdata $25.00")).toHaveLength(2);

    // A self-hosted provider without a key is fine; OpenAI has no models yet.
    const vllm = screen.getByRole("region", { name: "vLLM" });
    expect(within(vllm).getByText("Konfigurerad")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "OpenAI" })).toBeNull();

    await expectNoAxeViolations(document.body);
  });

  it("warns once about the missing key and the deprecated model that is still active", () => {
    renderPage();
    const banner = screen.getByText("Några modeller behöver åtgärdas").closest("[role=status]");
    expect(banner).toBeTruthy();
    expect(banner?.textContent).toContain("En leverantör saknar API-nyckel");
    expect(banner?.textContent).toContain("OpenAI");
    expect(banner?.textContent).toContain("En utfasad modell är fortfarande aktiv");
    expect(banner?.textContent).toContain("Claude 3.7 Sonnet");
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
    expect(screen.getByText("1 modell visas")).toBeTruthy();
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
