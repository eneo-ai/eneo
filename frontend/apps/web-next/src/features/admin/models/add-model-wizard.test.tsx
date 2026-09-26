// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SECURITY_CLASSIFICATIONS_KEY } from "@/features/admin/security-classifications/security-classifications";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";

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
  FAVORITES_KEY,
  type ModelProvider,
  PROVIDERS_KEY
} from "./model-providers";
import { type AdminModel, MODELS_KEY } from "./models";

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

function renderWizard({
  initialProviderId,
  models = []
}: { initialProviderId?: string; models?: AdminModel[] } = {}) {
  api.GET.mockImplementation((path: string) => {
    if (path.endsWith("/models/")) return ok(liveModels);
    if (path.endsWith("/model-defaults/")) return ok({ error: "not found" });
    return ok([]);
  });
  api.POST.mockImplementation((path: string) => {
    if (path === "/api/v1/admin/model-providers/") return ok({ ...existing, id: "p-new" });
    if (path.endsWith("/validate-model/")) return ok({ success: true });
    return ok({});
  });
  const queryClient = testQueryClient();
  queryClient.setQueryData(PROVIDERS_KEY, [existing]);
  queryClient.setQueryData(CAPABILITIES_KEY, capabilities);
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
    <AddModelWizard open onOpenChange={onOpenChange} initialProviderId={initialProviderId} />,
    { queryClient }
  );
  return { dialog: screen.getByRole("dialog", { name: "Lägg till modell" }), onOpenChange };
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
    const search = await within(dialog).findByRole("textbox", { name: "Filtrera katalogen" });
    // The step's first control, not the page.
    await waitFor(() => expect(document.activeElement).toBe(search));
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

  it("adds models to an existing provider through its own step", async () => {
    const { dialog } = renderWizard();

    fireEvent.click(within(dialog).getByRole("button", { name: "Välj en befintlig leverantör" }));

    const picker = within(dialog).getByRole("combobox", { name: "Leverantör" });
    // The step's first field, the provider picker.
    await waitFor(() => expect(document.activeElement).toBe(picker));
    expect(picker.textContent).toContain("Kommunens vLLM");
    fireEvent.click(within(dialog).getByRole("button", { name: "Nästa" }));
    expect(await within(dialog).findByRole("checkbox", { name: /gpt-5/ })).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });
});

describe("the add-model wizard's catalog", () => {
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
    expect(within(dialog).getByRole("alert").textContent).toContain("Model not found: gpt-5");
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
      expect(checkbox.disabled).toBe(true);
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
      expect(checkbox.disabled).toBe(false);
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
