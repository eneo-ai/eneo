// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
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

import { CAPABILITIES_KEY, type ModelProvider, PROVIDERS_KEY } from "./model-providers";
import { ProviderEditDialog } from "./provider-management";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const capabilities = {
  providers: {
    azure: {
      modes: ["completion"],
      models: {},
      fields: [
        { name: "api_key", required: true, secret: true, in: "credentials" },
        { name: "endpoint", required: true, secret: false, in: "config" },
        { name: "api_version", required: true, secret: false, in: "config" },
        { name: "deployment_name", required: true, secret: false, in: "config" }
      ]
    }
  },
  default_fields: [
    { name: "api_key", required: true, secret: true, in: "credentials" },
    { name: "endpoint", required: false, secret: false, in: "config" }
  ]
};

function provider(overrides: Partial<ModelProvider> = {}): ModelProvider {
  return {
    id: "p-openai",
    tenant_id: "t",
    name: "OpenAI",
    provider_type: "openai",
    config: {},
    is_active: true,
    masked_api_key: "...4f2a",
    key_expires_on: "2026-10-12",
    connection_check: null,
    connection_check_supported: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides
  };
}

/** The card's use: a button opens the dialog, which closes itself on save. */
function Opener({ item }: { item: ModelProvider }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Öppna
      </button>
      <ProviderEditDialog provider={item} open={open} onOpenChange={setOpen} />
    </>
  );
}

function renderDialog(item: ModelProvider = provider(), headerOptions = true) {
  api.PUT.mockImplementation(() => ok(item));
  const queryClient = testQueryClient();
  queryClient.setQueryData(PROVIDERS_KEY, [item]);
  queryClient.setQueryData(CAPABILITIES_KEY, capabilities);
  if (headerOptions)
    queryClient.setQueryData(["admin-model-provider-outbound-header-options"], {
      dynamic_values: [],
      supported_provider_types: ["hosted_vllm"],
      max_headers: 10
    });
  renderInApp(<Opener item={item} />, { queryClient });
  fireEvent.click(screen.getByRole("button", { name: "Öppna" }));
  return screen.getByRole("dialog", { name: "Redigera leverantör" });
}

const field = (name: RegExp) => screen.getByLabelText(name) as HTMLInputElement;
const save = (dialog: HTMLElement) =>
  fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

afterEach(() => vi.clearAllMocks());

describe("ProviderEditDialog", () => {
  it("shows the provider's settings as labelled Astryx fields", async () => {
    const dialog = renderDialog();

    expect(field(/^Leverantörsnamn/).value).toBe("OpenAI");
    // Required fields say so in text, not only with a mark (WCAG 3.3.2).
    expect(within(dialog).getByText("Leverantörsnamn").closest("label")?.textContent).toContain(
      "Obligatoriskt"
    );
    expect(
      within(dialog).getByRole("switch", { name: "Leverantören är aktiv" }).getAttribute("checked")
    ).not.toBeNull();
    const key = within(dialog).getByRole("group", { name: "API-nyckel" });
    expect(within(key).getByText("...4f2a")).toBeTruthy();
    expect(field(/^Nyckelns utgångsdatum/).value).toBe("12 oktober 2026");
    expect(field(/^Endpoint-URL/).value).toBe("");
    await expectNoAxeViolations(document.body);
  });

  it("moves focus into the new key's field and back when the change is dropped", async () => {
    const dialog = renderDialog();

    fireEvent.click(within(dialog).getByRole("button", { name: "Ändra API-nyckel" }));

    expect(document.activeElement).toBe(field(/^API-nyckel/));
    expect(field(/^Bekräfta API-nyckel/)).toBeTruthy();
    expect(within(dialog).getByText("Kommer att krypteras före lagring")).toBeTruthy();
    await expectNoAxeViolations(document.body);

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Avbryt och behåll nuvarande nyckel" })
    );

    expect(document.activeElement).toBe(
      within(dialog).getByRole("button", { name: "Ändra API-nyckel" })
    );
    expect(screen.queryByLabelText(/^Bekräfta API-nyckel/)).toBeNull();
  });

  it("shows an empty name at the field and moves focus there instead of saving", async () => {
    const dialog = renderDialog();
    fireEvent.change(field(/^Leverantörsnamn/), { target: { value: "  " } });

    save(dialog);

    expect(api.PUT).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(field(/^Leverantörsnamn/));
    expect(field(/^Leverantörsnamn/).getAttribute("aria-invalid")).toBe("true");
    const error = within(dialog).getByText("Ange ett namn på leverantören.");
    expect(field(/^Leverantörsnamn/).getAttribute("aria-describedby")).toContain(error.id);
    await expectNoAxeViolations(document.body);
  });

  it("asks for the new key, and for the same key twice", () => {
    const dialog = renderDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Ändra API-nyckel" }));

    save(dialog);

    expect(document.activeElement).toBe(field(/^API-nyckel/));
    expect(within(dialog).getByText("Ange API-nyckeln.")).toBeTruthy();

    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-new-5678" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "sk-new-5679" } });
    save(dialog);

    expect(api.PUT).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(field(/^Bekräfta API-nyckel/));
    expect(
      within(dialog).getByText("Nycklarna matchar inte. Skriv samma nyckel i båda fälten.")
    ).toBeTruthy();
  });

  it("saves the settings, a trimmed new key and the expiry date", async () => {
    const dialog = renderDialog();
    fireEvent.change(field(/^Leverantörsnamn/), { target: { value: " OpenAI prod " } });
    fireEvent.click(within(dialog).getByRole("switch", { name: "Leverantören är aktiv" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Ändra API-nyckel" }));
    // A pasted key often brings a trailing newline.
    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-new-5678\n" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "sk-new-5678\n" } });
    fireEvent.change(field(/^Nyckelns utgångsdatum/), { target: { value: "2026-11-30" } });

    save(dialog);

    await waitFor(() => expect(api.PUT).toHaveBeenCalledTimes(1));
    expect(api.PUT.mock.calls[0]).toEqual([
      "/api/v1/admin/model-providers/{provider_id}/",
      {
        params: { path: { provider_id: "p-openai" } },
        body: {
          name: "OpenAI prod",
          is_active: false,
          key_expires_on: "2026-11-30",
          credentials: { api_key: "sk-new-5678" },
          config: { endpoint: "" }
        }
      }
    ]);
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Leverantör uppdaterad"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("asks for the key again when the endpoint changes, and says why", async () => {
    const dialog = renderDialog();

    fireEvent.change(field(/^Endpoint-URL/), { target: { value: "https://proxy.kommun.se/v1" } });

    // The field opens by itself; focus stays where the admin is typing.
    expect(document.activeElement).not.toBe(field(/^API-nyckel/));
    expect(within(dialog).queryByRole("button", { name: "Ändra API-nyckel" })).toBeNull();
    expect(
      within(dialog).queryByRole("button", { name: "Avbryt och behåll nuvarande nyckel" })
    ).toBeNull();
    const why = within(dialog).getByText(
      "Du ändrade endpointen. Ange API-nyckeln igen; den lagrade nyckeln skickas inte till en annan destination."
    );
    expect(field(/^API-nyckel/).getAttribute("aria-describedby")).toContain(why.id);
    await expectNoAxeViolations(document.body);

    save(dialog);

    expect(api.PUT).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(field(/^API-nyckel/));
    expect(within(dialog).getByText("Ange API-nyckeln.")).toBeTruthy();

    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-new-5678" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "sk-new-5678" } });
    save(dialog);

    await waitFor(() => expect(api.PUT).toHaveBeenCalledTimes(1));
    expect(api.PUT.mock.calls[0]?.[1]).toMatchObject({
      body: {
        credentials: { api_key: "sk-new-5678" },
        config: { endpoint: "https://proxy.kommun.se/v1" }
      }
    });
  });

  it("keeps the stored key when the endpoint edit keeps the destination", async () => {
    const dialog = renderDialog(provider({ config: { endpoint: "https://api.example.com/v1" } }));

    fireEvent.change(field(/^Endpoint-URL/), { target: { value: "HTTPS://api.example.com/v1/" } });

    expect(within(dialog).getByRole("group", { name: "API-nyckel" })).toBeTruthy();
    save(dialog);

    await waitFor(() => expect(api.PUT).toHaveBeenCalledTimes(1));
    expect(api.PUT.mock.calls[0]?.[1]).toMatchObject({
      body: { config: { endpoint: "HTTPS://api.example.com/v1/" } }
    });
    expect(api.PUT.mock.calls[0]?.[1]).not.toHaveProperty("body.credentials");
  });

  it("does not ask for a key a provider without one never had", () => {
    const dialog = renderDialog(provider({ masked_api_key: null }));

    fireEvent.change(field(/^Endpoint-URL/), { target: { value: "https://proxy.kommun.se/v1" } });

    expect(within(dialog).getByRole("group", { name: "API-nyckel" })).toBeTruthy();
    expect(screen.queryByLabelText(/^Bekräfta API-nyckel/)).toBeNull();
  });

  it("rejects the masked display value as a key", async () => {
    const dialog = renderDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Ändra API-nyckel" }));
    fireEvent.change(field(/^API-nyckel/), { target: { value: "...4f2a" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "...4f2a" } });

    save(dialog);

    expect(api.PUT).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(field(/^API-nyckel/));
    const error = within(dialog).getByText(
      "Det ser ut som nyckelns maskerade visning. Ange den faktiska API-nyckeln."
    );
    expect(field(/^API-nyckel/).getAttribute("aria-describedby")).toContain(error.id);
    await expectNoAxeViolations(document.body);

    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-new-5678" } });
    expect(field(/^API-nyckel/).getAttribute("aria-invalid")).toBeNull();
  });

  it("shows the backend's refusal at the key field", async () => {
    const dialog = renderDialog();
    api.PUT.mockImplementation(() =>
      Promise.resolve({
        error: {
          message:
            "Changing the provider endpoint requires entering a new API key; the stored key is not reused for a different destination.",
          eneo_error_code: 9000
        },
        response: new Response("{}", { status: 400 })
      })
    );
    fireEvent.change(field(/^Endpoint-URL/), { target: { value: "https://proxy.kommun.se/v1" } });
    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-new-5678" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "sk-new-5678" } });

    save(dialog);

    const error = await within(dialog).findByText(/Changing the provider endpoint requires/);
    expect(document.activeElement).toBe(field(/^API-nyckel/));
    expect(field(/^API-nyckel/).getAttribute("aria-describedby")).toContain(error.id);
    expect(toast.error).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Redigera leverantör" })).toBe(dialog);

    // Another key: the refusal goes.
    fireEvent.change(field(/^API-nyckel/), { target: { value: "sk-new-9999" } });
    expect(field(/^API-nyckel/).getAttribute("aria-invalid")).toBeNull();
  });

  it("opens the key field for a refusal of a save that sent no key", async () => {
    const dialog = renderDialog();
    api.PUT.mockImplementation(() =>
      Promise.resolve({
        error: {
          message: "The API key looks like the masked display value; enter the actual key."
        },
        response: new Response("{}", { status: 400 })
      })
    );
    fireEvent.change(field(/^Leverantörsnamn/), { target: { value: "OpenAI prod" } });

    save(dialog);

    const error = await within(dialog).findByText(/masked display value/);
    expect(field(/^API-nyckel/).getAttribute("aria-describedby")).toContain(error.id);
    expect(document.activeElement).toBe(field(/^API-nyckel/));
  });

  it("removes a cleared expiry date", async () => {
    const dialog = renderDialog();

    fireEvent.click(within(dialog).getByRole("button", { name: "Rensa Nyckelns utgångsdatum" }));
    save(dialog);

    await waitFor(() => expect(api.PUT).toHaveBeenCalled());
    expect(api.PUT.mock.calls[0]?.[1]).toMatchObject({ body: { key_expires_on: null } });
  });

  it("asks for each required config field in its own words", async () => {
    const dialog = renderDialog(
      provider({
        id: "p-azure",
        name: "Azure",
        provider_type: "azure",
        config: {
          endpoint: "https://kommun.openai.azure.com",
          api_version: "",
          deployment_name: ""
        }
      })
    );
    const group = within(dialog).getByRole("group", { name: "Konfiguration" });

    save(dialog);

    expect(api.PUT).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(field(/^API-version/));
    expect(within(group).getByText("Ange API-versionen, till exempel 2024-10-21.")).toBeTruthy();
    expect(within(group).getByText("Ange distributionens namn från Azure-portalen.")).toBeTruthy();
    // The endpoint has a value: no error there.
    expect(field(/^Endpoint-URL/).getAttribute("aria-invalid")).toBeNull();
    await expectNoAxeViolations(document.body);
  });

  it("starts from the saved provider each time it opens", async () => {
    let dialog = renderDialog();
    fireEvent.change(field(/^Leverantörsnamn/), { target: { value: "Ändrat men inte sparat" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    // The <dialog>'s `close` event fires in a later task.
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Öppna" }));
    dialog = screen.getByRole("dialog", { name: "Redigera leverantör" });

    expect(within(dialog).getByLabelText<HTMLInputElement>(/^Leverantörsnamn/).value).toBe(
      "OpenAI"
    );
  });

  it("keeps focus while saving and stays open with what was typed when it fails", async () => {
    const dialog = renderDialog();
    let fail: () => void = () => {};
    api.PUT.mockImplementation(
      () =>
        new Promise((resolve) => {
          fail = () =>
            resolve({
              error: { message: "Internal error" },
              response: new Response("{}", { status: 500 })
            });
        })
    );
    fireEvent.change(field(/^Leverantörsnamn/), { target: { value: "OpenAI prod" } });
    const saveButton = within(dialog).getByRole("button", { name: "Spara" });
    saveButton.focus();

    fireEvent.click(saveButton);

    // Busy but not disabled: a disabled button would drop focus to the page.
    await waitFor(() => expect(saveButton.getAttribute("aria-busy")).toBe("true"));
    expect(saveButton.hasAttribute("disabled")).toBe(false);
    fireEvent.click(saveButton);
    expect(api.PUT).toHaveBeenCalledTimes(1);

    await act(async () => fail());

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Internal error", expect.anything())
    );
    expect(screen.getByRole("dialog", { name: "Redigera leverantör" })).toBe(dialog);
    expect(field(/^Leverantörsnamn/).value).toBe("OpenAI prod");
    expect(document.activeElement).toBe(saveButton);
  });

  it("shows a name another provider has at the name field", async () => {
    const dialog = renderDialog();
    api.PUT.mockImplementation(() =>
      Promise.resolve({
        error: { message: "Provider with name 'Azure' already exists", eneo_error_code: 9017 },
        response: new Response("{}", { status: 409 })
      })
    );
    fireEvent.change(field(/^Leverantörsnamn/), { target: { value: "Azure " } });

    save(dialog);

    const error = await within(dialog).findByText(
      "Det finns redan en leverantör som heter Azure. Ange ett annat namn."
    );
    expect(document.activeElement).toBe(field(/^Leverantörsnamn/));
    expect(field(/^Leverantörsnamn/).getAttribute("aria-describedby")).toContain(error.id);
    // The generic toast would speak of a model's display name.
    expect(toast.error).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);

    // Another name: the error goes.
    fireEvent.change(field(/^Leverantörsnamn/), { target: { value: "Azure Sverige" } });
    expect(field(/^Leverantörsnamn/).getAttribute("aria-invalid")).toBeNull();
  });
});

describe("provider outbound headers", () => {
  it("keeps preview search outside the provider save form", () => {
    renderDialog(provider({ provider_type: "hosted_vllm" }));
    expect(field(/^Sök på e-post/).form).toBeNull();
  });

  it("keeps a saved secret without sending its mask and allows a fixed value to change", async () => {
    const item = provider({
      provider_type: "hosted_vllm",
      outbound_headers: [
        {
          id: "h-secret",
          name: "X-Secret",
          value: "********",
          secret: true,
          encoding: "none",
          on_missing: "omit",
          fallback: null
        },
        {
          id: "h-region",
          name: "X-Region",
          value: "north",
          secret: false,
          encoding: "percent",
          on_missing: "omit",
          fallback: null
        }
      ]
    });
    const dialog = renderDialog(item);
    const header = await within(dialog).findByRole("group", { name: "X-Region" });
    fireEvent.change(within(header).getByLabelText(/^Värde/), { target: { value: "south" } });
    save(dialog);
    await waitFor(() => expect(api.PUT).toHaveBeenCalled());
    const body = api.PUT.mock.calls[0]![1].body;
    expect(body.outbound_headers).toEqual([
      {
        id: "h-secret",
        name: "X-Secret",
        secret: true,
        encoding: "none",
        on_missing: "omit",
        fallback: null
      },
      {
        id: "h-region",
        name: "X-Region",
        value: "south",
        secret: false,
        encoding: "percent",
        on_missing: "omit",
        fallback: null
      }
    ]);
    expect(JSON.stringify(body)).not.toContain("********");
  });
});

describe("outbound-header save boundaries", () => {
  const stored = provider({
    provider_type: "hosted_vllm",
    masked_api_key: null,
    config: { endpoint: "https://one.example/v1" },
    outbound_headers: [
      {
        id: "h",
        name: "X-Secret",
        value: "********",
        secret: true,
        encoding: "none",
        on_missing: "fallback",
        fallback: "********"
      }
    ]
  });
  it("requires secret value and fallback re-entry when the endpoint changes", async () => {
    const dialog = renderDialog(stored);
    fireEvent.change(field(/^Endpoint-URL/), { target: { value: "https://two.example/v1" } });
    save(dialog);
    expect(api.PUT).not.toHaveBeenCalled();
    expect(within(dialog).getByText(/Du ändrade endpointen/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Ändra värdet för X-Secret" }));
    fireEvent.change(field(/^Värde/), { target: { value: "new-value" } });
    save(dialog);
    expect(api.PUT).not.toHaveBeenCalled();
    fireEvent.click(
      within(dialog).getByRole("button", { name: /Ändra reservvärdet för X-Secret/ })
    );
    fireEvent.change(field(/^Reservvärde/), { target: { value: "new-fallback" } });
    save(dialog);
    await waitFor(() => expect(api.PUT).toHaveBeenCalledTimes(1));
    expect(api.PUT.mock.calls[0]![1].body.outbound_headers[0]).toMatchObject({
      value: "new-value",
      fallback: "new-fallback"
    });
  });

  it("omits saved headers when options fail and keeps the retry control focused", async () => {
    api.GET.mockRejectedValueOnce(new Error("offline"));
    const dialog = renderDialog(stored, false);
    expect(
      await within(dialog).findByText("Leverantörens sparade headers behålls oförändrade.")
    ).toBeTruthy();
    let resolve: ((result: unknown) => void) | undefined;
    api.GET.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const retry = within(dialog).getByRole("button", { name: "Försök igen" });
    retry.focus();
    fireEvent.click(retry);
    await waitFor(() => expect(retry.getAttribute("aria-busy")).toBe("true"));
    expect(document.activeElement).toBe(retry);
    save(dialog);
    await waitFor(() => expect(api.PUT).toHaveBeenCalledTimes(1));
    expect(api.PUT.mock.calls[0]![1].body).not.toHaveProperty("outbound_headers");
    await act(async () =>
      resolve?.({
        data: { dynamic_values: [], supported_provider_types: ["hosted_vllm"], max_headers: 10 },
        response: new Response("{}")
      })
    );
  });

  it("shows an API refusal in the form and preserves input for retry", async () => {
    const item = provider({
      provider_type: "hosted_vllm",
      outbound_headers: [
        {
          id: "h",
          name: "Bad Header",
          value: "north",
          secret: false,
          encoding: "none",
          on_missing: "omit",
          fallback: null
        }
      ]
    });
    const dialog = renderDialog(item);
    api.PUT.mockResolvedValueOnce({
      error: { message: "Invalid outbound header name: Bad Header", eneo_error_code: 9007 },
      response: new Response("{}", { status: 400 })
    });
    save(dialog);
    const problem = await within(dialog).findByText("Invalid outbound header name: Bad Header");
    expect(document.activeElement?.getAttribute("aria-describedby")).toContain(problem.id);
    expect((within(dialog).getByLabelText(/^Headernamn/) as HTMLInputElement).value).toBe(
      "Bad Header"
    );
    fireEvent.change(within(dialog).getByLabelText(/^Headernamn/), {
      target: { value: "X-Region" }
    });
    save(dialog);
    await waitFor(() => expect(api.PUT).toHaveBeenCalledTimes(2));
    expect(api.PUT.mock.calls[1]![1].body.outbound_headers[0].name).toBe("X-Region");
  });
});
