// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), info: vi.fn(), warning: vi.fn(), error: vi.fn() }
}));

import { CAPABILITIES_KEY, type ModelProvider, PROVIDERS_KEY } from "./model-providers";
import type { ModelsPresentation } from "./models";
import { ProviderOverview } from "./provider-overview";

const model = (id: string, nickname: string, providerId: string) => ({
  id,
  name: id,
  nickname,
  is_deprecated: false,
  is_org_enabled: true,
  is_org_default: false,
  provider_id: providerId,
  security_classification: null,
  supported_model_kwargs: {}
});

const presentation = {
  completion_models: [
    model("c1", "Claude Opus", "p-anthropic"),
    model("c2", "GPT-5", "p-openai"),
    model("c3", "Llama", "p-groq")
  ],
  embedding_models: [model("e1", "E5 Large", "p-vllm")],
  transcription_models: []
} as unknown as ModelsPresentation;

function provider(id: string, name: string, overrides: Partial<ModelProvider> = {}): ModelProvider {
  return {
    id,
    tenant_id: "t",
    name,
    provider_type: "openai",
    config: {},
    is_active: true,
    masked_api_key: "...4f2a",
    key_expires_on: null,
    connection_check: null,
    connection_check_supported: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides
  };
}

const providers = [
  provider("p-anthropic", "Anthropic", {
    provider_type: "anthropic",
    connection_check: {
      status: "failed",
      checked_at: "2026-09-26T07:00:00Z",
      error: "authentication_failed"
    }
  }),
  provider("p-openai", "OpenAI", { key_expires_on: "2026-10-12" }),
  provider("p-vllm", "vLLM", { provider_type: "hosted_vllm", key_expires_on: "2026-09-20" }),
  // A key is required, but there is none and no models: no card to go to.
  provider("p-mistral", "Mistral", { provider_type: "mistral", masked_api_key: null }),
  // Nothing to fix.
  provider("p-groq", "Groq", {
    connection_check: { status: "ok", checked_at: "2026-09-26T07:00:00Z", error: null }
  })
];

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

function renderOverview(items: ModelProvider[] = providers) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(PROVIDERS_KEY, items);
  queryClient.setQueryData(CAPABILITIES_KEY, capabilities);
  renderInApp(
    <ProviderOverview
      models={presentation}
      classifications={[]}
      securityEnabled={false}
      onAddModel={vi.fn()}
      onAddProvider={vi.fn()}
    />,
    { queryClient }
  );
}

function banner(title: string) {
  const element = screen.getByText(title).closest<HTMLElement>(".astryx-banner-frame");
  if (!element) throw new Error(`No banner titled ${title}`);
  return element;
}

beforeEach(() => {
  // Only Date: React Query and Astryx keep their real timers.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 8, 26, 10));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("the models page's attention banner", () => {
  it("lists providers that need attention in their cards' words", async () => {
    renderOverview();
    const attention = banner("4 leverantörer behöver åtgärdas");
    const rows = within(attention).getAllByRole("listitem");

    expect(rows.map((row) => row.textContent)).toEqual([
      "MistralNyckel saknas",
      "AnthropicAnslutningen misslyckades: API-nyckeln godkändes inte",
      "OpenAINyckeln går ut 12 okt.",
      "vLLMNyckeln har gått ut 20 sep."
    ]);
    // An error among them (failed, expired) makes the banner an error.
    expect(attention.querySelector("[data-status='error']")).toBeTruthy();
    // The same words the card uses.
    const anthropic = screen.getByRole("region", { name: "Anthropic" });
    expect(
      within(anthropic).getByText("Anslutningen misslyckades: API-nyckeln godkändes inte")
    ).toBeTruthy();
    expect(
      within(screen.getByRole("region", { name: "vLLM" })).getByText("Nyckeln har gått ut 20 sep.")
    ).toBeTruthy();
    // Not a live region: the check that changes it announces its own result.
    expect(attention.closest("[role=status], [role=alert], [aria-live]")).toBeNull();
    await expectNoAxeViolations(document.body);
  });

  it("links each provider with a card; one without models is plain text", () => {
    renderOverview();
    const attention = banner("4 leverantörer behöver åtgärdas");

    expect(
      within(attention)
        .getAllByRole("link")
        .map((link) => [link.textContent, link.getAttribute("href")])
    ).toEqual([
      ["Anthropic", "#provider-p-anthropic"],
      ["OpenAI", "#provider-p-openai"],
      ["vLLM", "#provider-p-vllm"]
    ]);
    expect(within(attention).queryByRole("link", { name: "Mistral" })).toBeNull();
  });

  it("moves focus to the provider's card", () => {
    renderOverview();
    const link = within(banner("4 leverantörer behöver åtgärdas")).getByRole("link", {
      name: "OpenAI"
    });
    link.focus();

    // What Enter on a focused link does.
    fireEvent.click(link);

    const card = screen.getByRole("region", { name: "OpenAI" });
    expect(document.activeElement).toBe(card);
    // Focusable by script only, so it is no extra tab stop.
    expect(card.tabIndex).toBe(-1);
  });

  it("clears the filters that hide the card before moving focus to it", () => {
    renderOverview();
    const search = screen.getByRole("textbox", { name: "Sök modeller och leverantörer" });
    fireEvent.change(search, { target: { value: "E5" } });
    expect(screen.queryByRole("region", { name: "Anthropic" })).toBeNull();

    fireEvent.click(
      within(banner("4 leverantörer behöver åtgärdas")).getByRole("link", { name: "Anthropic" })
    );

    expect((search as HTMLInputElement).value).toBe("");
    expect(document.activeElement).toBe(screen.getByRole("region", { name: "Anthropic" }));
  });

  it("warns without error when nothing has failed or expired", () => {
    renderOverview([
      provider("p-openai", "OpenAI", { key_expires_on: "2026-10-26" }),
      provider("p-groq", "Groq")
    ]);
    const attention = banner("En leverantör behöver åtgärdas");

    expect(within(attention).getByText("Nyckeln går ut 26 okt.")).toBeTruthy();
    expect(attention.querySelector("[data-status='warning']")).toBeTruthy();
    expect(
      within(attention).getByText(
        "Gå till leverantören för att testa anslutningen igen. Nyckel och utgångsdatum byter du under Redigera leverantör i leverantörens meny."
      )
    ).toBeTruthy();
  });

  it("shows no banner when every provider is fine", () => {
    renderOverview([provider("p-openai", "OpenAI"), provider("p-groq", "Groq")]);

    expect(screen.queryByText(/behöver åtgärdas/)).toBeNull();
  });
});
