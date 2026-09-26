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

function renderDialog(item: ModelProvider = provider()) {
  api.PUT.mockImplementation(() => ok(item));
  const queryClient = testQueryClient();
  queryClient.setQueryData(PROVIDERS_KEY, [item]);
  queryClient.setQueryData(CAPABILITIES_KEY, capabilities);
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
