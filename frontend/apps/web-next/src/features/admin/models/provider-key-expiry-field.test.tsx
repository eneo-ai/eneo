// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), info: vi.fn(), warning: vi.fn(), error: vi.fn() }
}));

import { AddModelWizard } from "./add-model-wizard";
import {
  CAPABILITIES_KEY,
  FAVORITES_KEY,
  type ModelProvider,
  PROVIDERS_KEY
} from "./model-providers";
import { ProviderEditDialog } from "./provider-management";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const capabilities = {
  providers: {
    openai: {
      modes: ["completion"],
      models: {},
      fields: [{ name: "api_key", required: true, secret: true, in: "credentials" }]
    }
  },
  default_fields: [{ name: "api_key", required: true, secret: true, in: "credentials" }]
};

const provider: ModelProvider = {
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
  updated_at: "2026-01-01T00:00:00Z"
};

function seededClient(providers: ModelProvider[]) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(PROVIDERS_KEY, providers);
  queryClient.setQueryData(CAPABILITIES_KEY, capabilities);
  queryClient.setQueryData(FAVORITES_KEY, []);
  return queryClient;
}

function expiryField() {
  return screen.getByRole("combobox", { name: /Nyckelns utgångsdatum/ });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the provider dialog's key expiry", () => {
  function renderDialog() {
    api.PUT.mockImplementation(() => ok(provider));
    renderInApp(<ProviderEditDialog provider={provider} open onOpenChange={vi.fn()} />, {
      queryClient: seededClient([provider])
    });
    return screen.getByRole("dialog", { name: /Redigera leverantör/ });
  }

  it("is an optional, labelled date field with help text", async () => {
    const dialog = renderDialog();

    const field = expiryField();
    expect((field as HTMLInputElement).value).toBe("12 oktober 2026");
    expect(within(dialog).getByText(/ange datumet själv/)).toBeTruthy();
    expect(field.getAttribute("aria-describedby")).toBeTruthy();
    expect(within(dialog).getByText("Valfritt")).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("saves a typed date", async () => {
    const dialog = renderDialog();

    fireEvent.change(expiryField(), { target: { value: "2026-11-30" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await waitFor(() => expect(api.PUT).toHaveBeenCalled());
    expect(api.PUT.mock.calls[0]?.[1]).toMatchObject({
      params: { path: { provider_id: "p-openai" } },
      body: { key_expires_on: "2026-11-30" }
    });
  });

  it("removes a cleared date", async () => {
    const dialog = renderDialog();

    fireEvent.click(within(dialog).getByRole("button", { name: "Rensa Nyckelns utgångsdatum" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await waitFor(() => expect(api.PUT).toHaveBeenCalled());
    expect(api.PUT.mock.calls[0]?.[1]).toMatchObject({ body: { key_expires_on: null } });
  });
});

describe("the add-provider wizard's key expiry", () => {
  it("is sent with the new provider", async () => {
    api.POST.mockImplementation(() => ok({ ...provider, key_expires_on: "2027-03-01" }));
    api.GET.mockImplementation(() => ok([]));
    renderInApp(<AddModelWizard open onOpenChange={vi.fn()} />, {
      queryClient: seededClient([])
    });

    fireEvent.click(screen.getByRole("button", { name: "Lägg till OpenAI" }));
    // The labels end in a required marker ("API-nyckel*").
    fireEvent.change(screen.getByLabelText(/^API-nyckel/), { target: { value: "sk-test-1234" } });
    fireEvent.change(screen.getByLabelText(/^Bekräfta API-nyckel/), {
      target: { value: "sk-test-1234" }
    });
    fireEvent.change(expiryField(), { target: { value: "2027-03-01" } });
    await expectNoAxeViolations(document.body);
    fireEvent.click(screen.getByRole("button", { name: "Nästa" }));

    await waitFor(() => expect(api.POST).toHaveBeenCalled());
    expect(api.POST.mock.calls[0]).toEqual([
      "/api/v1/admin/model-providers/",
      {
        body: {
          name: "OpenAI",
          provider_type: "openai",
          credentials: { api_key: "sk-test-1234" },
          config: {},
          key_expires_on: "2027-03-01"
        }
      }
    ]);
  });
});
