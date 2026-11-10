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
const liveTranscriptionModels = [{ name: "pianissimo-sv", mode: "transcription" }];

function renderWizard({
  initialProviderId,
  models = [],
  providersLoaded = true,
  caps = capabilities,
  fixedKind,
  onCreated,
  imageModels = liveImageModels,
  providerList = [existing],
  capsLoaded = true
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
} = {}) {
  api.GET.mockImplementation(
    (path: string, options?: { params?: { query?: { mode?: string } } }) => {
      if (path.endsWith("/models/")) {
        const mode = options?.params?.query?.mode;
        if (mode === "image") return ok(imageModels);
        if (mode === "rerank") return ok(liveRerankModels);
        if (mode === "transcription") return ok(liveTranscriptionModels);
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
        "Ange den om leverantören är självhostad eller har en egen endpoint."
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

  function renderTranscriptionStep(providerType: string) {
    return renderWizard({
      initialProviderId: "p-vllm",
      fixedKind: "transcription",
      providerList: [{ ...existing, provider_type: providerType }],
      caps: {
        ...capabilities,
        providers: {
          [providerType]: { ...capabilities.providers.openai, modes: ["transcription"] }
        }
      }
    });
  }

  it("creates a transcription model with live transcription on a vLLM provider", async () => {
    const { dialog, onOpenChange } = renderTranscriptionStep("hosted_vllm");
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /pianissimo-sv/ }));
    const live = within(dialog).getByRole("checkbox", { name: /^Livetranskribering/ });
    expect((live as HTMLInputElement).checked).toBe(false);
    fireEvent.click(live);
    await expectNoAxeViolations(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/transcription/", {
      body: expect.objectContaining({ name: "pianissimo-sv", supports_realtime: true })
    });
  });

  it("says why live transcription is unavailable and creates the model without it", async () => {
    const { dialog, onOpenChange } = renderTranscriptionStep("openai");
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /pianissimo-sv/ }));
    const live = within(dialog).getByRole("checkbox", { name: /^Livetranskribering/ });
    // Astryx keeps a disabled checkbox focusable; a press changes nothing.
    expect(live.getAttribute("aria-disabled")).toBe("true");
    expect(within(dialog).getByText("Kräver en leverantör av typen vLLM.")).toBeTruthy();
    fireEvent.click(live);
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till 1 modell" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/tenant-models/transcription/", {
      body: expect.objectContaining({ name: "pianissimo-sv", supports_realtime: false })
    });
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
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
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
