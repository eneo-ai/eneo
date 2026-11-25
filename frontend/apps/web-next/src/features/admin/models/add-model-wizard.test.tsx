// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SECURITY_CLASSIFICATIONS_KEY } from "@/features/admin/security-classifications/security-classifications";
import { expectNoAxeViolations } from "@/test/axe";
import { flushAnnouncements, renderInApp, testQueryClient } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn() }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

import { AddModelWizard } from "./add-model-wizard";
import {
  CAPABILITIES_KEY,
  OUTBOUND_HEADER_OPTIONS_KEY,
  FAVORITES_KEY,
  type ModelProvider,
  PROVIDERS_KEY
} from "./model-providers";
import { type AdminModel, MODELS_KEY } from "./models";
import type { ModelKind } from "./models";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const capabilities = {
  providers: {
    openai: {
      modes: ["completion"],
      models: {},
      fields: [
        { name: "api_key", required: true, secret: true, in: "credentials" },
        { name: "endpoint", required: false, secret: false, in: "config" }
      ]
    }
  },
  default_fields: [{ name: "api_key", required: true, secret: true, in: "credentials" }]
};

const existing: ModelProvider = {
  id: "p-vllm",
  tenant_id: "t",
  name: "Kommunens vLLM",
  provider_type: "openai",
  config: {},
  is_active: true,
  realtime_eligibility: "endpoint_required",
  masked_api_key: "...4f2a",
  key_expires_on: null,
  connection_check: null,
  connection_check_supported: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z"
};

/** The provider's live model list: one the catalog knows, one it does not. */
const liveModels = [
  {
    name: "gpt-5",
    mode: "completion",
    max_input_tokens: 272000,
    max_output_tokens: 128000,
    supports_vision: true,
    supports_function_calling: true,
    supports_reasoning: true,
    input_cost_per_token: 0.00000125
  },
  { name: "kommun-llama", mode: "completion", supports_vision: false }
];

/** A model the tenant has already, as the admin model list returns it. */
function tenantModel(overrides: Partial<AdminModel>): AdminModel {
  return {
    id: `m-${overrides.name}`,
    name: "model",
    nickname: null,
    provider_id: "p-vllm",
    is_deprecated: false,
    ...overrides
  } as AdminModel;
}

/** The provider's image models, served when the list is asked for that mode. */
const liveImageModels = [
  { name: "gpt-image-1", display_name: "GPT Image 1", mode: "image", cost_per_image: 0.04 }
];

/** The provider's rerank models, served when the list is asked for that mode. */
const liveRerankModels = [{ name: "Qwen/Qwen3-Reranker-4B", mode: "rerank" }];

/** The provider's transcription models, served when the list is asked for that mode. */
const liveTranscriptionModels = [
  { name: "pianissimo-sv", mode: "transcription" },
  { name: "forte-sv", mode: "transcription" }
];

function renderWizard({
  initialProviderId,
  models = [],
  providersLoaded = true,
  caps = capabilities,
  fixedKind,
  onCreated,
  imageModels = liveImageModels,
  providerList = [existing],
  capsLoaded = true,
  transcriptionList = liveTranscriptionModels
}: {
  initialProviderId?: string;
  models?: AdminModel[];
  providersLoaded?: boolean;
  caps?: {
    providers: Record<string, typeof capabilities.providers.openai>;
    default_fields: typeof capabilities.default_fields;
  };
  fixedKind?: ModelKind;
  onCreated?: (ids: string[]) => void;
  imageModels?: typeof liveImageModels;
  providerList?: ModelProvider[];
  capsLoaded?: boolean;
  /** What the provider's list answers for transcription: models, or `[{ error }]`. */
  transcriptionList?: unknown[];
} = {}) {
  api.GET.mockImplementation(
    (path: string, options?: { params?: { query?: { mode?: string } } }) => {
      if (path.endsWith("/models/")) {
        const mode = options?.params?.query?.mode;
        if (mode === "image") return ok(imageModels);
        if (mode === "rerank") return ok(liveRerankModels);
        if (mode === "transcription") return ok(transcriptionList);
        if (mode === "embedding")
          return ok([
            { name: "multilingual-e5-large", mode: "embedding", output_vector_size: 1024 }
          ]);
        return ok(liveModels);
      }
      if (path.endsWith("/model-defaults/")) return ok({ error: "not found" });
      if (path === "/api/v1/admin/model-providers/") return ok(providerList);
      if (path === "/api/v1/admin/model-providers/capabilities/") return new Promise(() => {});
      return ok([]);
    }
  );
  api.POST.mockImplementation((path: string) => {
    if (path === "/api/v1/admin/model-providers/") return ok({ ...existing, id: "p-new" });
    if (path.endsWith("/validate-model/")) return ok({ success: true });
    return ok({});
  });
  const queryClient = testQueryClient();
  if (providersLoaded) queryClient.setQueryData(PROVIDERS_KEY, providerList);
  if (capsLoaded) queryClient.setQueryData(CAPABILITIES_KEY, caps);
  queryClient.setQueryData(OUTBOUND_HEADER_OPTIONS_KEY, {
    dynamic_values: [],
    supported_provider_types: ["hosted_vllm"],
    max_headers: 10
  });
  queryClient.setQueryData(FAVORITES_KEY, []);
  queryClient.setQueryData(MODELS_KEY, {
    completion_models: models,
    embedding_models: [],
    transcription_models: [],
    image_models: []
  });
  queryClient.setQueryData(SECURITY_CLASSIFICATIONS_KEY, {
    security_enabled: false,
    security_classifications: []
  });
  const onOpenChange = vi.fn();
  renderInApp(
    <AddModelWizard
      open
      onOpenChange={onOpenChange}
      initialProviderId={initialProviderId}
      fixedKind={fixedKind}
      onCreated={onCreated}
    />,
    { queryClient }
  );
  return {
    dialog: screen.getByRole("dialog", { name: "Lägg till modell" }),
    onOpenChange,
    queryClient
  };
}

const field = (name: RegExp) => screen.getByLabelText(name) as HTMLInputElement;

/** The texts a control's aria-describedby points at, joined. */
const describedBy = (element: HTMLElement) =>
  (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ");

async function toCredentials() {
  const { dialog } = renderWizard();
  fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till OpenAI" }));
  await waitFor(() => expect(within(dialog).getByText("Uppgifter")).toBeTruthy());
  return dialog;
}

async function toModels(models: AdminModel[] = []) {
  const result = renderWizard({ initialProviderId: "p-vllm", models });
  await waitFor(() =>
    expect(within(result.dialog).getByRole("checkbox", { name: /gpt-5/ })).toBeTruthy()
  );
  // The loaded list's count is said on its own, not joined to what a test does next.
  await flushAnnouncements();
  return result;
}

afterEach(() => vi.clearAllMocks());

describe("the add-provider wizard's credentials", () => {
  it("moves focus to the first field when a provider is picked", async () => {
    const dialog = await toCredentials();

    expect(document.activeElement).toBe(field(/^Leverantörsnamn/));
    expect(field(/^Leverantörsnamn/).value).toBe("OpenAI");
    // The endpoint is optional, the key is not; the hint no longer repeats it.
    expect(within(dialog).getByText(/^API-nyckel/).textContent).toContain("Obligatoriskt");
    expect(
      within(dialog).getByText(
        "Ange den om leverantören är självhostad eller har en egen endpoint. Livetext använder vLLM:s realtids-API (/v1/realtime) på servern."
      )
    ).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("shows a missing key, then keys that differ, at their fields", async () => {
    const dialog = await toCredentials();
    const next = within(dialog).getByRole("button", { name: "Nästa" });

    fireEvent.click(next);

    expect(document.activeElement).toBe(field(/^API-nyckel/));
    expect(within(dialog).getByText("Ange API-nyckeln.")).toBeTruthy();

    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-live-1234" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "sk-live-1235" } });
    fireEvent.click(next);

    expect(document.activeElement).toBe(field(/^Bekräfta API-nyckel/));
    expect(
      within(dialog).getByText("Nycklarna matchar inte. Skriv samma nyckel i båda fälten.")
    ).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);
  });

  it("says the type is fixed and where live text streams from, before the provider is saved", async () => {
    const dialog = await toCredentials();
    // One line: for OpenAI the type note is followed by when vLLM fits better.
    expect(
      within(dialog).getByText(
        "Typen kan inte ändras efteråt. Har en annan aktör modellen bakom ett OpenAI-kompatibelt API passar oftast vLLM bättre. Där är nyckeln valfri och utgående headers fungerar. OpenAI med egen Endpoint-URL fungerar också, men kräver en nyckel."
      )
    ).toBeTruthy();
    const endpoint = field(/^Endpoint-URL/);
    const help = (endpoint.getAttribute("aria-describedby") ?? "")
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ");
    expect(help).toContain("Livetext använder vLLM:s realtids-API (/v1/realtime) på servern.");
  });

  it("asks for the vLLM server's address with /v1, and keeps the gateway note", async () => {
    const { dialog } = renderWizard({
      caps: {
        providers: {
          hosted_vllm: {
            modes: ["transcription"],
            models: {},
            fields: [{ name: "endpoint", required: true, secret: false, in: "config" }]
          }
        },
        default_fields: []
      }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till vLLM" }));
    await waitFor(() => expect(field(/^Endpoint-URL/)).toBeTruthy());
    expect(describedBy(field(/^Endpoint-URL/))).toContain(
      "Adressen till vLLM-servern, med /v1 på slutet. Livetext använder vLLM:s realtids-API (/v1/realtime) på servern."
    );
    expect(
      within(dialog).getByText(
        "Typen kan inte ändras efteråt. Finns din gateway redan som OpenAI-leverantör kan du använda den för livetext."
      )
    ).toBeTruthy();
  });

  it("creates the provider with its key expiry and moves on to its models", async () => {
    const dialog = await toCredentials();
    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-live-1234" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "sk-live-1234" } });
    fireEvent.change(field(/^Nyckelns utgångsdatum/), { target: { value: "2027-03-01" } });

    fireEvent.click(within(dialog).getByRole("button", { name: "Nästa" }));

    await waitFor(() => expect(api.POST).toHaveBeenCalled());
    expect(api.POST.mock.calls[0]).toEqual([
      "/api/v1/admin/model-providers/",
      {
        body: {
          name: "OpenAI",
          provider_type: "openai",
          credentials: { api_key: "sk-live-1234" },
          config: {},
          key_expires_on: "2027-03-01"
        }
      }
    ]);
    const hosting = await within(dialog).findByRole("combobox", { name: /^Hosting-region/ });
    // Focus follows the step's first setting.
    await waitFor(() => expect(document.activeElement).toBe(hosting));
    expect(within(dialog).getByText("Modeller")).toBeTruthy();
  });

  it("shows a name another provider has at the name field", async () => {
    const dialog = await toCredentials();
    api.POST.mockImplementation(() =>
      Promise.resolve({
        error: { message: "Provider with name 'OpenAI' already exists", eneo_error_code: 9017 },
        response: new Response("{}", { status: 409 })
      })
    );
    // An empty name falls back to "OpenAI", which is taken.
    fireEvent.change(field(/^Leverantörsnamn/), { target: { value: "" } });
    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-live-1234" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "sk-live-1234" } });

    fireEvent.click(within(dialog).getByRole("button", { name: "Nästa" }));

    expect(
      await within(dialog).findByText(
        "Det finns redan en leverantör som heter OpenAI. Ange ett annat namn."
      )
    ).toBeTruthy();
    expect(document.activeElement).toBe(field(/^Leverantörsnamn/));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("goes back to the gallery with what was typed kept", async () => {
    const dialog = await toCredentials();
    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-live-1234" } });

    fireEvent.click(within(dialog).getByRole("button", { name: "Tillbaka" }));

    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(dialog).getByRole("textbox", { name: "Sök leverantörer" })
      )
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till OpenAI" }));
    await waitFor(() => expect(field(/^API-nyckel/).value).toBe("sk-live-1234"));
  });

  it("clears credentials when switching provider type", async () => {
    const { dialog } = renderWizard({
      caps: {
        ...capabilities,
        providers: { ...capabilities.providers, anthropic: capabilities.providers.openai }
      }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till OpenAI" }));
    await waitFor(() => expect(field(/^API-nyckel/)).toBeTruthy());
    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-openai-secret" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "sk-openai-secret" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Tillbaka" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till Anthropic" }));
    await waitFor(() => expect(field(/^API-nyckel/).value).toBe(""));
    expect(field(/^Bekräfta API-nyckel/).value).toBe("");
    // A type that cannot carry live text gets the type note alone.
    expect(within(dialog).getByText("Typen kan inte ändras efteråt.")).toBeTruthy();
    expect(within(dialog).queryByText(/gateway/)).toBeNull();
  });

  it("adds models to an existing provider through its own step", async () => {
    const { dialog } = renderWizard();

    fireEvent.click(within(dialog).getByRole("button", { name: "Välj en befintlig leverantör" }));

    const picker = within(dialog).getByRole("combobox", { name: /^Leverantör/ });
    // The step's first field, the provider picker.
    await waitFor(() => expect(document.activeElement).toBe(picker));
    expect(picker.textContent).toContain("Kommunens vLLM");
    fireEvent.click(within(dialog).getByRole("button", { name: "Nästa" }));
    expect(await within(dialog).findByRole("checkbox", { name: /gpt-5/ })).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("asks for an existing provider at its picker instead of disabling Nästa", async () => {
    // The providers arrive after the wizard opened: none is preselected.
    const { dialog } = renderWizard({ providersLoaded: false });
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "Välj en befintlig leverantör" })
    );
    const next = within(dialog).getByRole("button", { name: "Nästa" });
    expect(next.hasAttribute("disabled")).toBe(false);

    next.focus();
    fireEvent.click(next);

    const picker = within(dialog).getByRole("combobox", { name: /^Leverantör/ });
    expect(document.activeElement).toBe(picker);
    expect(within(dialog).getByText("Välj en leverantör.")).toBeTruthy();
    expect(within(dialog).queryByRole("checkbox", { name: /gpt-5/ })).toBeNull();
    await expectNoAxeViolations(document.body);
  });
});

describe("the add-model wizard's catalog", () => {
  it.each(["validation", "creation"])(
    "allows closing again after model %s fails",
    async (phase) => {
      const { dialog, onOpenChange } = renderWizard({
        initialProviderId: "p-vllm",
        fixedKind: "image",
        caps: {
          ...capabilities,
          providers: { openai: { ...capabilities.providers.openai, modes: ["image"] } }
        }
      });
      api.POST.mockImplementation((path: string) =>
        path.endsWith("/validate-model/")
          ? phase === "validation"
            ? ok({ success: false, error: "fixture refusal" })
            : ok({ success: true })
          : Promise.resolve({
              error: { message: "fixture refusal" },
              response: new Response("{}", { status: 400 })
            })
      );
      fireEvent.click(await within(dialog).findByRole("checkbox", { name: /GPT Image 1/ }));
      fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));
      if (phase === "creation") await waitFor(() => expect(toast.error).toHaveBeenCalled());
      else await within(dialog).findByText("fixture refusal");
      fireEvent.click(within(dialog).getByRole("button", { name: "Stäng" }));
      await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    }
  );
  it.each(["validation", "creation"])(
    "keeps the image wizard open during model %s",
    async (phase) => {
      const { dialog, onOpenChange } = renderWizard({
        initialProviderId: "p-vllm",
        fixedKind: "image",
        caps: {
          ...capabilities,
          providers: { openai: { ...capabilities.providers.openai, modes: ["image"] } }
        }
      });
      let finish!: (response: unknown) => void;
      const pending = new Promise((resolve) => {
        finish = resolve;
      });
      api.POST.mockImplementation((path: string) =>
        path.endsWith("/validate-model/")
          ? phase === "validation"
            ? pending
            : ok({ success: true })
          : phase === "creation"
            ? pending
            : ok({ id: "created-image" })
      );
      fireEvent.click(await within(dialog).findByRole("checkbox", { name: /GPT Image 1/ }));
      fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));
      await waitFor(() =>
        expect(
          api.POST.mock.calls.some(([path]) =>
            phase === "validation"
              ? path.endsWith("/validate-model/")
              : path.endsWith("/tenant-models/image/")
          )
        ).toBe(true)
      );
      fireEvent.click(within(dialog).getByRole("button", { name: "Stäng" }));
      expect(onOpenChange).not.toHaveBeenCalled();
      await act(async () =>
        finish(
          phase === "validation"
            ? { data: { success: true }, response: new Response() }
            : { data: { id: "created-image" }, response: new Response() }
        )
      );
      await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    }
  );
  it.each([0, 1, 2])("reports only fulfilled IDs when %s image creations fail", async (failed) => {
    const onCreated = vi.fn();
    const { dialog, onOpenChange } = renderWizard({
      initialProviderId: "p-vllm",
      fixedKind: "image",
      onCreated,
      imageModels: [
        ...liveImageModels,
        { name: "gpt-image-2", display_name: "GPT Image 2", mode: "image", cost_per_image: 0.04 }
      ],
      caps: {
        ...capabilities,
        providers: { openai: { ...capabilities.providers.openai, modes: ["completion", "image"] } }
      }
    });
    api.POST.mockImplementation((path: string, { body }: { body: { name: string } }) => {
      if (path.endsWith("/validate-model/")) return ok({ success: true });
      if (failed === 2 || (failed === 1 && body.name === "gpt-image-1"))
        return Promise.resolve({
          error: { message: "fixture refusal" },
          response: new Response("{}", { status: 400 })
        });
      return ok({ id: body.name });
    });
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /GPT Image 1/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /GPT Image 2/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 2 modeller" }));
    if (failed === 2) {
      await waitFor(() => expect(toast.error).toHaveBeenCalled());
      expect(onCreated).not.toHaveBeenCalled();
      expect(onOpenChange).not.toHaveBeenCalled();
      expect(
        (within(dialog).getByRole("checkbox", { name: /GPT Image 1/ }) as HTMLInputElement).checked
      ).toBe(true);
    } else {
      await waitFor(() =>
        expect(onCreated).toHaveBeenCalledWith(
          failed === 1 ? ["gpt-image-2"] : ["gpt-image-1", "gpt-image-2"]
        )
      );
      expect(onOpenChange).toHaveBeenCalledWith(false);
      if (failed === 1) expect(toast.warning).toHaveBeenCalledWith("La till 1 av 2 modeller");
    }
  });

  it("filters both provider choices to image-capable types", async () => {
    const { dialog } = renderWizard({
      fixedKind: "image",
      providerList: [
        existing,
        { ...existing, id: "chat-only", name: "Endast chatt", provider_type: "anthropic" }
      ],
      caps: {
        ...capabilities,
        providers: {
          openai: { ...capabilities.providers.openai, modes: ["completion", "image"] },
          anthropic: { ...capabilities.providers.openai, modes: ["completion"] }
        }
      }
    });
    expect(within(dialog).getByRole("button", { name: "Lägg till OpenAI" })).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: /Lägg till Anthropic/ })).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Välj en befintlig leverantör" }));
    fireEvent.keyDown(within(dialog).getByRole("combobox", { name: /^Leverantör/ }), {
      key: "Enter"
    });
    expect(await screen.findByRole("option", { name: existing.name })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Endast chatt" })).toBeNull();
  });

  it("waits for capabilities without starting a completion catalog in an image flow", async () => {
    const { dialog, queryClient } = renderWizard({
      initialProviderId: "p-vllm",
      fixedKind: "image",
      capsLoaded: false
    });
    expect(api.GET.mock.calls.some(([path]) => path.endsWith("/models/"))).toBe(false);
    await act(async () =>
      queryClient.setQueryData(CAPABILITIES_KEY, {
        ...capabilities,
        providers: { openai: { ...capabilities.providers.openai, modes: ["completion", "image"] } }
      })
    );
    expect(await within(dialog).findByRole("checkbox", { name: /GPT Image 1/ })).toBeTruthy();
    expect(
      api.GET.mock.calls
        .filter(([path]) => path.endsWith("/models/"))
        .every(([, options]) => options.params.query.mode === "image")
    ).toBe(true);
  });
  it("locks image creation to image-capable providers and reports the created IDs", async () => {
    const onCreated = vi.fn();
    const { dialog } = renderWizard({
      initialProviderId: "p-vllm",
      fixedKind: "image",
      onCreated,
      caps: {
        ...capabilities,
        providers: { openai: { ...capabilities.providers.openai, modes: ["completion", "image"] } }
      }
    });
    api.POST.mockImplementation((path: string) =>
      path.endsWith("/validate-model/") ? ok({ success: true }) : ok({ id: "new-image" })
    );
    const pick = await within(dialog).findByRole("checkbox", { name: /GPT Image 1/ });
    expect(within(dialog).queryByRole("combobox", { name: /^Modelltyp/ })).toBeNull();
    expect(within(dialog).queryByRole("checkbox", { name: /gpt-5/ })).toBeNull();
    fireEvent.click(pick);
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(["new-image"]));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/image/", expect.anything());
  });
  it("lists the provider's models with their capabilities and price", async () => {
    const { dialog } = await toModels();

    const gpt = within(dialog).getByRole("checkbox", { name: /gpt-5/ });
    expect(gpt.getAttribute("aria-describedby")).toBeTruthy();
    expect(within(dialog).getByText("2 modeller hittade")).toBeTruthy();
    expect(within(dialog).getAllByText("Bild").length).toBeGreaterThan(0);
    expect(within(dialog).getByText(/\$1\.25 \/ 1M/)).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("asks for a model at the list instead of adding nothing", async () => {
    const { dialog } = await toModels();

    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till modeller" }));

    expect(
      within(dialog).getByText("Välj minst en modell, eller lägg till en med dess id.")
    ).toBeTruthy();
    expect(document.activeElement).toBe(within(dialog).getByRole("checkbox", { name: /gpt-5/ }));
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);
  });

  it("asks for the token limits the catalog does not know", async () => {
    const { dialog, onOpenChange } = await toModels();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /kommun-llama/ }));
    const limits = within(dialog).getByRole("group", { name: "kommun-llama" });

    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));

    const input = within(limits).getByLabelText(/^Max indatatokens/) as HTMLInputElement;
    expect(document.activeElement).toBe(input);
    expect(within(limits).getAllByText("Ange ett heltal större än 0.")).toHaveLength(2);
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);

    // NumberInput commits on blur.
    fireEvent.change(input, { target: { value: "32768" } });
    fireEvent.blur(input);
    const output = within(limits).getByLabelText(/^Max utdatatokens/) as HTMLInputElement;
    fireEvent.change(output, { target: { value: "4096" } });
    fireEvent.blur(output);
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/completion/", {
      body: expect.objectContaining({
        name: "kommun-llama",
        max_input_tokens: 32768,
        max_output_tokens: 4096
      })
    });
    expect(toast.success).toHaveBeenCalledWith("1 modell tillagd");
  });

  it("adds a model by its id to the top of the list, ticked", async () => {
    const { dialog } = await toModels();
    const id = within(dialog).getByRole("textbox", { name: "Saknas modellen? Lägg till med id" });

    fireEvent.change(id, { target: { value: "kommun-mistral" } });
    fireEvent.keyDown(id, { key: "Enter" });

    const added = await within(dialog).findByRole("checkbox", { name: /kommun-mistral/ });
    expect((added as HTMLInputElement).checked).toBe(true);
    expect(within(dialog).getAllByRole("checkbox")[0]).toBe(added);
    expect((id as HTMLInputElement).value).toBe("");
    await waitFor(() =>
      expect(document.querySelector("[data-astryx-live-region='polite']")?.textContent).toBe(
        "1 modell vald"
      )
    );
  });

  it("asks before creating models the provider did not accept", async () => {
    const { dialog, onOpenChange } = await toModels();
    api.POST.mockImplementation((path: string) =>
      path.endsWith("/validate-model/")
        ? ok({ success: false, error: "Model not found: gpt-5" })
        : ok({})
    );
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /gpt-5/ }));

    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));

    const acknowledge = await within(dialog).findByRole("checkbox", {
      name: "Jag förstår att valideringen misslyckades och vill skapa modellen ändå."
    });
    expect(document.activeElement).toBe(acknowledge);
    expect(within(dialog).getByRole("alert").textContent).toBe(
      "Vissa modeller kunde inte verifieras"
    );
    // What failed is read with the checkbox that acknowledges it.
    const description = acknowledge
      .getAttribute("aria-describedby")!
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent)
      .join(" ");
    expect(description).toContain("Model not found: gpt-5");
    await expectNoAxeViolations(document.body);

    // Not acknowledged: the press leads back to the question.
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa ändå" }));
    expect(document.activeElement).toBe(acknowledge);

    fireEvent.click(acknowledge);
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa ändå" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/admin/tenant-models/completion/",
      expect.anything()
    );
  });

  it("marks the models the provider has already, which cannot be picked again", async () => {
    const { dialog } = await toModels([
      // The same model…
      tenantModel({ name: "gpt-5", nickname: "GPT-5 (upphandling)" }),
      // …or another under the name a pick would get (unique per provider).
      tenantModel({ name: "llama-3-70b", nickname: "Kommun-Llama" })
    ]);
    const description = (checkbox: HTMLElement) =>
      (checkbox.getAttribute("aria-describedby") ?? "")
        .split(" ")
        .map((id) => document.getElementById(id)?.textContent ?? "")
        .join(" ");

    for (const name of [/gpt-5/, /kommun-llama/]) {
      const checkbox = within(dialog).getByRole("checkbox", { name }) as HTMLInputElement;
      expect(checkbox.getAttribute("aria-disabled")).toBe("true");
      // Said in words, not only by the dimmed box.
      expect(description(checkbox)).toContain("Tillagd");
    }
    await expectNoAxeViolations(document.body);
  });

  it("counts only the provider's own, current models as added", async () => {
    const { dialog } = await toModels([
      tenantModel({ name: "gpt-5", provider_id: "p-other" }),
      tenantModel({ name: "kommun-llama", is_deprecated: true })
    ]);

    for (const name of [/gpt-5/, /kommun-llama/]) {
      const checkbox = within(dialog).getByRole("checkbox", { name }) as HTMLInputElement;
      expect(checkbox.hasAttribute("aria-disabled")).toBe(false);
    }
    expect(within(dialog).queryByText(/Tillagd/)).toBeNull();
  });

  it("says at the id field when the provider has that model already", async () => {
    const { dialog } = await toModels([tenantModel({ name: "kommun-mistral" })]);
    const id = within(dialog).getByRole("textbox", { name: "Saknas modellen? Lägg till med id" });
    id.focus();

    fireEvent.change(id, { target: { value: "kommun-mistral" } });
    fireEvent.keyDown(id, { key: "Enter" });

    const error = within(dialog).getByText(
      "Leverantören har redan kommun-mistral. Ange ett annat modell-id."
    );
    expect(id.getAttribute("aria-invalid")).toBe("true");
    expect(id.getAttribute("aria-describedby")).toContain(error.id);
    expect(document.activeElement).toBe(id);
    expect(within(dialog).queryByRole("checkbox", { name: /kommun-mistral/ })).toBeNull();
    expect(api.GET).not.toHaveBeenCalledWith(
      expect.stringContaining("model-defaults"),
      expect.anything()
    );
    await expectNoAxeViolations(document.body);

    // Typing again clears it.
    fireEvent.change(id, { target: { value: "kommun-mistral-2" } });
    expect(id.getAttribute("aria-invalid")).toBeNull();
  });

  it("creates an image model with its per-image price and the auto request defaults", async () => {
    const imageCapable = {
      ...capabilities,
      providers: { openai: { ...capabilities.providers.openai, modes: ["completion", "image"] } }
    };
    const { dialog, onOpenChange } = renderWizard({
      initialProviderId: "p-vllm",
      caps: imageCapable
    });
    // The provider does both: the type is chosen in the step.
    const type = await within(dialog).findByRole("combobox", { name: /^Modelltyp/ });
    expect(type.textContent).toContain("Chatt");
    fireEvent.keyDown(type, { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "Bildgenerering" }));

    const pick = await within(dialog).findByRole("checkbox", { name: /GPT Image 1/ });
    expect(within(dialog).getByText(/\$0\.04\/bild/)).toBeTruthy();
    expect(within(dialog).queryByRole("checkbox", { name: /gpt-5/ })).toBeNull();
    fireEvent.click(pick);
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/admin/model-providers/{provider_id}/validate-model/",
      {
        params: { path: { provider_id: "p-vllm" } },
        body: { model_name: "gpt-image-1", model_type: "image" }
      }
    );
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/image/", {
      body: {
        provider_id: "p-vllm",
        name: "gpt-image-1",
        display_name: "GPT Image 1",
        family: "openai",
        hosting: "usa",
        cost_per_image: 0.04,
        default_size: "auto",
        default_quality: "auto",
        security_classification: null
      }
    });
    expect(toast.success).toHaveBeenCalledWith("1 modell tillagd");
  });

  it("lets an embedding model use E5 and an explicitly chosen hosting region", async () => {
    const { dialog, onOpenChange } = renderWizard({
      initialProviderId: "p-vllm",
      fixedKind: "embedding",
      caps: {
        ...capabilities,
        providers: { openai: { ...capabilities.providers.openai, modes: ["embedding"] } }
      }
    });
    const hosting = await within(dialog).findByRole("combobox", { name: /^Hosting-region/ });
    expect(hosting.textContent).toContain("USA");
    fireEvent.keyDown(hosting, { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "Frankrike" }));
    fireEvent.keyDown(within(dialog).getByRole("combobox", { name: /^Modellfamilj/ }), {
      key: "Enter"
    });
    fireEvent.click(await screen.findByRole("option", { name: "E5 (HuggingFace)" }));
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /multilingual-e5-large/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/embedding/", {
      body: expect.objectContaining({ family: "e5", hosting: "fra" })
    });
  });

  it("creates a rerank model, leaving factor and cap to the backend's defaults", async () => {
    const rerankCapable = {
      ...capabilities,
      providers: { openai: { ...capabilities.providers.openai, modes: ["completion", "rerank"] } }
    };
    const { dialog, onOpenChange } = renderWizard({
      initialProviderId: "p-vllm",
      caps: rerankCapable
    });
    const type = await within(dialog).findByRole("combobox", { name: /^Modelltyp/ });
    fireEvent.keyDown(type, { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "Rerankning" }));

    const pick = await within(dialog).findByRole("checkbox", { name: /Qwen3-Reranker-4B/ });
    expect(within(dialog).queryByRole("checkbox", { name: /gpt-5/ })).toBeNull();
    fireEvent.click(pick);
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.GET).toHaveBeenCalledWith(
      "/api/v1/admin/model-providers/{provider_id}/models/",
      expect.objectContaining({ params: expect.objectContaining({ query: { mode: "rerank" } }) })
    );
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/admin/model-providers/{provider_id}/validate-model/",
      {
        params: { path: { provider_id: "p-vllm" } },
        body: { model_name: "Qwen/Qwen3-Reranker-4B", model_type: "rerank" }
      }
    );
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/rerank/", {
      body: {
        provider_id: "p-vllm",
        name: "Qwen/Qwen3-Reranker-4B",
        display_name: "Qwen/Qwen3-Reranker-4B",
        family: "openai",
        hosting: "usa",
        security_classification: null
      }
    });
    expect(toast.success).toHaveBeenCalledWith("1 modell tillagd");
  });

  const transcriptionCaps = {
    ...capabilities,
    providers: { openai: { ...capabilities.providers.openai, modes: ["transcription"] } }
  };

  function renderTranscriptionStep(eligibility: ModelProvider["realtime_eligibility"]) {
    return renderWizard({
      initialProviderId: "p-vllm",
      fixedKind: "transcription",
      providerList: [{ ...existing, realtime_eligibility: eligibility }],
      caps: transcriptionCaps
    });
  }

  it("creates a transcription model with live text on a provider that carries it", async () => {
    const { dialog, onOpenChange } = renderTranscriptionStep("eligible");
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /pianissimo-sv/ }));
    const live = within(dialog).getByRole("checkbox", { name: /^Livetext$/ });
    expect((live as HTMLInputElement).checked).toBe(false);
    fireEvent.click(live);
    await expectNoAxeViolations(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/transcription/", {
      body: expect.objectContaining({ name: "pianissimo-sv", supports_realtime: true })
    });
  });

  it.each([
    [
      "endpoint_required",
      "Livetext kräver att leverantörens Endpoint-URL går till en server eller gateway med vLLM:s realtids-API. OpenAI:s egen tjänst har inte det API:t."
    ],
    [
      "unsupported_provider",
      "Livetext kräver en leverantör av typen vLLM, eller OpenAI med en Endpoint-URL till en server med vLLM:s realtids-API."
    ],
    [
      "outbound_headers_configured",
      "Livetext kan inte skicka utgående headers. Lägg modellen på en leverantör utan sådana, eller ta bort dem på leverantören om inget annat behöver dem."
    ],
    ["provider_inactive", "Leverantören är avstängd, så den kan inte bära livetext."]
  ] as const)(
    "says why live text is locked when the provider says %s",
    async (eligibility, reason) => {
      const { dialog, onOpenChange } = renderTranscriptionStep(eligibility);
      fireEvent.click(await within(dialog).findByRole("checkbox", { name: /pianissimo-sv/ }));
      const live = within(dialog).getByRole("checkbox", { name: /^Livetext$/ });
      // Locked but reachable: Astryx keeps it out of native disabled, so Tab stops
      // on it and the reason is read; a press changes nothing.
      expect(live.getAttribute("aria-disabled")).toBe("true");
      expect(live.hasAttribute("disabled")).toBe(false);
      live.focus();
      expect(document.activeElement).toBe(live);
      expect(describedBy(live)).toContain(reason);
      fireEvent.click(live);
      fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));

      await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/transcription/", {
        body: expect.objectContaining({ name: "pianissimo-sv", supports_realtime: false })
      });
    }
  );

  it("marks live text per model when several are picked", async () => {
    const { dialog, onOpenChange } = renderTranscriptionStep("eligible");
    const catalog = await within(dialog).findByRole("group", { name: "Modeller att lägga till" });
    // Nothing to mark before a model is picked.
    expect(within(dialog).queryByRole("checkbox", { name: /^Livetext$/ })).toBeNull();
    fireEvent.click(within(catalog).getByRole("checkbox", { name: /pianissimo-sv/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /^Livetext$/ }));
    fireEvent.click(within(catalog).getByRole("checkbox", { name: /forte-sv/ }));

    // One row per picked model, outside the list they were picked in; the
    // mark made with one model picked stays with that model.
    const live = within(dialog).getByRole("group", { name: "Livetext" });
    expect(
      within(dialog).getByText(
        "Markera bara modeller som visar texten medan någon spelar in. En modell för ljudfiler ska inte ha livetext. Modellens server behöver stödja vLLM:s realtids-API."
      )
    ).toBeTruthy();
    const pianissimo = within(live).getByRole("checkbox", { name: "pianissimo-sv" });
    const forte = within(live).getByRole("checkbox", { name: "forte-sv" });
    expect((pianissimo as HTMLInputElement).checked).toBe(true);
    expect((forte as HTMLInputElement).checked).toBe(false);
    await expectNoAxeViolations(dialog);

    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 2 modeller" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/transcription/", {
      body: expect.objectContaining({ name: "pianissimo-sv", supports_realtime: true })
    });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/transcription/", {
      body: expect.objectContaining({ name: "forte-sv", supports_realtime: false })
    });
  });

  it("keeps one locked live text box with its reason when several are picked", async () => {
    const { dialog } = renderTranscriptionStep("endpoint_required");
    const catalog = await within(dialog).findByRole("group", { name: "Modeller att lägga till" });
    fireEvent.click(within(catalog).getByRole("checkbox", { name: /pianissimo-sv/ }));
    fireEvent.click(within(catalog).getByRole("checkbox", { name: /forte-sv/ }));

    const live = within(dialog).getByRole("checkbox", { name: /^Livetext$/ });
    expect(live.getAttribute("aria-disabled")).toBe("true");
    expect(describedBy(live)).toContain(
      "Livetext kräver att leverantörens Endpoint-URL går till en server eller gateway med vLLM:s realtids-API."
    );
    expect(within(dialog).queryByRole("group", { name: "Livetext" })).toBeNull();
  });

  /** Creates a provider in the wizard; the list keeps answering without it, as a refetch still in flight would. */
  async function createProviderThatSays(
    eligibility: ModelProvider["realtime_eligibility"]
  ): Promise<HTMLElement> {
    const { dialog } = renderWizard({ fixedKind: "transcription", caps: transcriptionCaps });
    api.POST.mockImplementation((path: string) =>
      path === "/api/v1/admin/model-providers/"
        ? ok({ ...existing, id: "p-new", realtime_eligibility: eligibility })
        : ok({})
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till OpenAI" }));
    await waitFor(() => expect(field(/^API-nyckel/)).toBeTruthy());
    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-live-1234" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "sk-live-1234" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Nästa" }));
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /pianissimo-sv/ }));
    return within(dialog).getByRole("checkbox", { name: /^Livetext$/ });
  }

  it("uses the new provider's own answer before the provider list is fetched again", async () => {
    const live = await createProviderThatSays("eligible");
    expect(live.getAttribute("aria-disabled")).not.toBe("true");
  });

  it("says why a provider just created cannot carry live text", async () => {
    const live = await createProviderThatSays("endpoint_required");
    expect(live.getAttribute("aria-disabled")).toBe("true");
    expect(describedBy(live)).toContain(
      "Livetext kräver att leverantörens Endpoint-URL går till en server eller gateway med vLLM:s realtids-API. OpenAI:s egen tjänst har inte det API:t."
    );
  });

  it("shows the reason on a line of its own with a lock, and reads it with the help", async () => {
    const live = await createProviderThatSays("endpoint_required");
    const lines = (live.getAttribute("aria-describedby") ?? "")
      .split(" ")
      .map((id) => document.getElementById(id));
    // The reason comes first: Astryx puts the caller's description before its own.
    expect(lines.map((line) => line?.textContent)).toEqual([
      "Livetext kräver att leverantörens Endpoint-URL går till en server eller gateway med vLLM:s realtids-API. OpenAI:s egen tjänst har inte det API:t.",
      "Visar texten medan någon spelar in. Modellens server behöver stödja vLLM:s realtids-API."
    ]);
    const reason = lines.find(
      (line) =>
        line?.textContent ===
        "Livetext kräver att leverantörens Endpoint-URL går till en server eller gateway med vLLM:s realtids-API. OpenAI:s egen tjänst har inte det API:t."
    );
    expect(reason?.querySelector("svg[aria-hidden='true']")).not.toBeNull();
  });

  it("never shows another provider's answer after going back to pick a different one", async () => {
    const gateway = { ...existing, id: "p-gw", name: "Gateway", realtime_eligibility: "eligible" };
    const other = { ...existing, id: "p-other", name: "Annan leverantör" };
    const { dialog, queryClient } = renderWizard({
      initialProviderId: "p-gw",
      fixedKind: "transcription",
      providerList: [gateway, other] as ModelProvider[],
      caps: transcriptionCaps
    });
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /pianissimo-sv/ }));
    expect(
      within(dialog)
        .getByRole("checkbox", { name: /^Livetext$/ })
        .getAttribute("aria-disabled")
    ).not.toBe("true");

    fireEvent.click(within(dialog).getByRole("button", { name: "Tillbaka" }));
    const picker = await within(dialog).findByRole("combobox", { name: /^Leverantör/ });
    fireEvent.click(picker);
    const list = await waitFor(() =>
      document.getElementById(picker.getAttribute("aria-controls") ?? "")!
    );
    fireEvent.click(await within(list).findByRole("option", { name: "Annan leverantör" }));
    // Fetched again meanwhile, without the chosen provider: its answer is not known.
    act(() => queryClient.setQueryData(PROVIDERS_KEY, [gateway]));
    fireEvent.click(within(dialog).getByRole("button", { name: "Nästa" }));

    // Asks for a provider again instead of offering live text on the first one's word.
    expect(await within(dialog).findByText("Välj en leverantör.")).toBeTruthy();
    expect(within(dialog).queryByRole("checkbox", { name: /^Livetext$/ })).toBeNull();
  });

  it("keeps the picks when the list is filtered", async () => {
    const { dialog } = await toModels();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /gpt-5/ }));

    fireEvent.change(within(dialog).getByRole("textbox", { name: "Filtrera katalogen" }), {
      target: { value: "llama" }
    });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /kommun-llama/ }));

    await act(async () => {});
    expect(within(dialog).getByText("2 modeller valda")).toBeTruthy();
  });
});

describe("the model step for a server at an address of its own", () => {
  const whisper = { name: "whisper-1", mode: "transcription", cost_per_minute: 0.006 };
  const catalogCaps = {
    providers: {
      openai: {
        ...capabilities.providers.openai,
        modes: ["transcription"],
        models: { transcription: [whisper] }
      },
      hosted_vllm: {
        modes: ["transcription"],
        models: { transcription: [whisper] },
        fields: [{ name: "endpoint", required: true, secret: false, in: "config" }]
      },
      azure: { ...capabilities.providers.openai, modes: ["transcription"], models: {} }
    },
    default_fields: capabilities.default_fields
  };
  const gateway: ModelProvider = {
    ...existing,
    id: "p-gw",
    name: "Gateway",
    config: { endpoint: "https://gateway.example/v1" }
  };
  const vllm: ModelProvider = {
    ...existing,
    id: "p-own-vllm",
    name: "Aktörens vLLM",
    provider_type: "hosted_vllm",
    config: { endpoint: "https://vllm.example/v1" }
  };
  const liveRegion = () =>
    document.querySelector("[data-astryx-live-region='polite']")?.textContent;

  function renderStep(provider: ModelProvider, transcriptionList: unknown[]) {
    return renderWizard({
      initialProviderId: provider.id,
      fixedKind: "transcription",
      providerList: [provider],
      caps: catalogCaps,
      transcriptionList
    });
  }

  it("shows no built-in models when the server lists none, and says it once", async () => {
    const { dialog } = renderStep(gateway, []);

    const title = "Eneo hittade ingen modell av typen Transkription i serverns lista";
    expect(await within(dialog).findByText(title)).toBeTruthy();
    expect(
      within(dialog).getByText("Skriv modellens id nedan, som det står hos den som kör servern.")
    ).toBeTruthy();
    expect(within(dialog).queryByRole("checkbox", { name: /whisper-1/ })).toBeNull();
    expect(within(dialog).queryByText(/modeller hittade/)).toBeNull();
    expect(within(dialog).queryByText("Inga modeller hittades")).toBeNull();
    expect(
      within(dialog).getByRole("textbox", { name: "Saknas modellen? Lägg till med id" })
    ).toBeTruthy();
    await waitFor(() => expect(liveRegion()).toBe(title));
    await expectNoAxeViolations(document.body);
  });

  it("says the server sent no list, never its own error text", async () => {
    const { dialog } = renderStep(vllm, [
      { error: "Failed to list models: ConnectError('All connection attempts failed')" }
    ]);

    const title = "Servern skickade ingen modellista";
    expect(await within(dialog).findByText(title)).toBeTruthy();
    expect(
      within(dialog).getByText(
        "Kontrollera adressen och nyckeln. Du kan också skriva modellens id nedan."
      )
    ).toBeTruthy();
    expect(within(dialog).queryByText(/Failed to list models/)).toBeNull();
    expect(within(dialog).queryByText(/Visar den inbyggda katalogen/)).toBeNull();
    expect(within(dialog).queryByRole("checkbox", { name: /whisper-1/ })).toBeNull();
    await waitFor(() => expect(liveRegion()).toBe(title));
    await expectNoAxeViolations(document.body);
  });

  it("lists the server's own models as before", async () => {
    const { dialog } = renderStep(gateway, liveTranscriptionModels);

    expect(await within(dialog).findByRole("checkbox", { name: /pianissimo-sv/ })).toBeTruthy();
    expect(within(dialog).getByText("2 modeller hittade")).toBeTruthy();
    expect(within(dialog).queryByRole("checkbox", { name: /whisper-1/ })).toBeNull();
  });

  it("keeps the built-in catalog for a provider without an address", async () => {
    const { dialog } = renderStep(existing, []);

    expect(await within(dialog).findByRole("checkbox", { name: /whisper-1/ })).toBeTruthy();
    expect(within(dialog).getByText("1 modell hittad")).toBeTruthy();
    expect(within(dialog).queryByText(/Eneo hittade/)).toBeNull();
  });

  it("asks where a server of its own stands instead of guessing the region", async () => {
    const { dialog, onOpenChange } = renderStep(gateway, liveTranscriptionModels);

    const hosting = await within(dialog).findByRole("combobox", { name: /^Hosting-region/ });
    expect(hosting.textContent).not.toContain("USA");
    expect(hosting.textContent).toContain("Välj region");
    expect(describedBy(hosting)).toContain(
      "Var servern som kör modellen står. Eneo kan inte se det, så välj själv."
    );
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /pianissimo-sv/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));

    expect(document.activeElement).toBe(hosting);
    expect(within(dialog).getByText("Välj var servern står.")).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);

    fireEvent.keyDown(hosting, { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "Sverige" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/transcription/", {
      body: expect.objectContaining({ name: "pianissimo-sv", hosting: "swe" })
    });
  });

  it("asks for the region of a provider just created with an address", async () => {
    const { dialog } = renderWizard({ fixedKind: "transcription", caps: catalogCaps });
    api.POST.mockImplementation(
      (path: string, options?: { body?: { config?: Record<string, string> } }) =>
        path === "/api/v1/admin/model-providers/"
          ? ok({ ...existing, id: "p-new", config: options?.body?.config ?? {} })
          : ok({})
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till OpenAI" }));
    await waitFor(() => expect(field(/^API-nyckel/)).toBeTruthy());
    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-live-1234" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "sk-live-1234" } });
    fireEvent.change(field(/^Endpoint-URL/), { target: { value: "https://gateway.example/v1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Nästa" }));

    const hosting = await within(dialog).findByRole("combobox", { name: /^Hosting-region/ });
    expect(hosting.textContent).toContain("Välj region");
  });

  /**
   * Creates a vLLM provider in the wizard whose connection check answers
   * `check`, while its model list answers `list`.
   */
  async function createVllmChecked(
    check: ModelProvider["connection_check"],
    list: unknown[],
    kind: ModelKind = "transcription"
  ) {
    const caps = {
      ...catalogCaps,
      providers: {
        hosted_vllm: { ...catalogCaps.providers.hosted_vllm, modes: [kind] }
      }
    };
    const result = renderWizard({ fixedKind: kind, caps, transcriptionList: list });
    // The server keeps what it was given, so a refetch sees it.
    let stored: ModelProvider[] = [existing];
    api.GET.mockImplementation((path: string) => {
      if (path.endsWith("/models/")) return ok(list);
      if (path === "/api/v1/admin/model-providers/") return ok(stored);
      return ok([]);
    });
    const created = (config: Record<string, string>): ModelProvider => ({
      ...existing,
      id: "p-new",
      name: "vLLM",
      provider_type: "hosted_vllm",
      config
    });
    api.POST.mockImplementation(
      (path: string, options?: { body?: { config?: Record<string, string> } }) => {
        if (path === "/api/v1/admin/model-providers/") {
          const provider = created(options?.body?.config ?? {});
          stored = [existing, provider];
          return ok(provider);
        }
        if (path.endsWith("/connection-check/")) {
          const provider = { ...stored[1]!, connection_check: check };
          stored = [existing, provider];
          return ok(provider);
        }
        return ok({});
      }
    );
    fireEvent.click(within(result.dialog).getByRole("button", { name: "Lägg till vLLM" }));
    fireEvent.change(await waitFor(() => field(/^Endpoint-URL/)), {
      target: { value: "https://dead.example/v1" }
    });
    fireEvent.click(within(result.dialog).getByRole("button", { name: "Nästa" }));
    return result;
  }
  const checkedAt = "2026-11-25T10:00:00Z";
  const connectionChecks = () =>
    api.POST.mock.calls.filter(([path]) => String(path).endsWith("/connection-check/"));

  it("checks a provider just created once, and says when its server did not answer", async () => {
    const { dialog, queryClient } = await createVllmChecked(
      { status: "failed", error: "unreachable", checked_at: checkedAt },
      [{ error: "Failed to list models: ConnectError" }]
    );

    const title = "Servern svarade inte på https://dead.example/v1";
    expect(await within(dialog).findByText(title)).toBeTruthy();
    expect(
      within(dialog).getByText(
        "Kontrollera adressen med Redigera leverantör i menyn på leverantörens kort under Modeller."
      )
    ).toBeTruthy();
    // One banner: not the list's own as well, and no line about live text.
    expect(within(dialog).queryByText("Servern skickade ingen modellista")).toBeNull();
    expect(within(dialog).queryByText(/livetext/)).toBeNull();
    await waitFor(() => expect(liveRegion()).toBe(title));
    expect(connectionChecks()).toHaveLength(1);
    // The card no longer says "Inte testad".
    await waitFor(() =>
      expect(
        queryClient
          .getQueryData<ModelProvider[]>(PROVIDERS_KEY)
          ?.find((provider) => provider.id === "p-new")?.connection_check?.status
      ).toBe("failed")
    );
    await expectNoAxeViolations(document.body);
  });

  it("never says a server that answered cannot be reached", async () => {
    const { dialog } = await createVllmChecked(
      { status: "failed", error: "not_found", checked_at: checkedAt },
      [{ error: "Failed to list models: 404" }]
    );

    expect(
      await within(dialog).findByText("Servern svarade, men skickade ingen modellista")
    ).toBeTruthy();
    expect(
      within(dialog).getByText(
        "Skriv modellens id nedan. En server som bara ger livetext kan sakna modellista. Är adressen fel ändrar du den med Redigera leverantör i menyn på leverantörens kort under Modeller."
      )
    ).toBeTruthy();
    expect(within(dialog).queryByText(/svarade inte/)).toBeNull();
    expect(within(dialog).queryByText(/misslyckades/)).toBeNull();
  });

  it("keeps the live text line to transcription", async () => {
    const { dialog } = await createVllmChecked(
      { status: "failed", error: "not_found", checked_at: checkedAt },
      [{ error: "Failed to list models: 404" }],
      "completion"
    );

    expect(
      await within(dialog).findByText("Servern svarade, men skickade ingen modellista")
    ).toBeTruthy();
    expect(within(dialog).queryByText(/livetext/)).toBeNull();
  });

  it("claims neither when no request may have reached the server", async () => {
    const { dialog } = await createVllmChecked(
      { status: "failed", error: "authentication_failed", checked_at: checkedAt },
      [{ error: "Failed to list models: 401" }]
    );

    expect(await within(dialog).findByText("Servern skickade ingen modellista")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "Kontrollera adressen och nyckeln med Redigera leverantör i menyn på leverantörens kort under Modeller. Du kan också skriva modellens id nedan."
      )
    ).toBeTruthy();
    expect(within(dialog).queryByText(/svarade/)).toBeNull();
  });

  it("does not check a provider that was there before", async () => {
    const { dialog } = renderStep(vllm, []);

    expect(await within(dialog).findByText(/Eneo hittade ingen modell/)).toBeTruthy();
    expect(connectionChecks()).toHaveLength(0);
  });

  it("treats Azure, which always has an address, as the cloud service it is", async () => {
    const { dialog } = renderStep(
      {
        ...existing,
        id: "p-azure",
        provider_type: "azure",
        config: { endpoint: "https://kommun.openai.azure.com" }
      },
      []
    );

    const hosting = await within(dialog).findByRole("combobox", { name: /^Hosting-region/ });
    expect(hosting.textContent).toContain("Sverige");
    expect(within(dialog).getByRole("textbox", { name: "Ange ett modell-id" })).toBeTruthy();
    expect(within(dialog).queryByText(/Eneo hittade/)).toBeNull();
    expect(within(dialog).queryByText(/Servern skickade/)).toBeNull();
  });
});

it("creates supported providers with validated headers and keeps rejected input for retry", async () => {
  const { dialog } = renderWizard({
    caps: {
      providers: {
        hosted_vllm: {
          modes: ["completion"],
          models: {},
          fields: [{ name: "endpoint", required: true, secret: false, in: "config" }]
        }
      },
      default_fields: []
    }
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till vLLM" }));
  fireEvent.change(field(/^Endpoint-URL/), { target: { value: "https://gateway.example/v1" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till header" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Nästa" }));
  expect(api.POST).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(field(/^Headernamn/));
  fireEvent.change(field(/^Headernamn/), { target: { value: "X-Region" } });
  fireEvent.change(field(/^Värde/), { target: { value: "north" } });
  api.POST.mockResolvedValueOnce({
    error: { message: "Header is reserved", eneo_error_code: 9007 },
    response: new Response("{}", { status: 400 })
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Nästa" }));
  const error = await within(dialog).findByText("Header is reserved");
  expect(document.activeElement?.getAttribute("aria-describedby")).toContain(error.id);
  expect(field(/^Värde/).value).toBe("north");
  fireEvent.change(field(/^Headernamn/), { target: { value: "X-Custom-Region" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Nästa" }));
  // Two creates; the second is followed by the new provider's connection check.
  await waitFor(() =>
    expect(
      api.POST.mock.calls.filter(([path]) => path === "/api/v1/admin/model-providers/")
    ).toHaveLength(2)
  );
  expect(api.POST.mock.calls[1]![1].body).toMatchObject({
    provider_type: "hosted_vllm",
    config: { endpoint: "https://gateway.example/v1" },
    outbound_headers: [
      {
        name: "X-Custom-Region",
        value: "north",
        secret: false,
        encoding: "percent",
        on_missing: "omit",
        fallback: null
      }
    ]
  });
});
