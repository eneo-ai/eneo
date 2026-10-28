// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Button } from "@/components/ui/button";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { CreateApiKeyDialog } from "./api-key-form";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

function serve(constraints: object) {
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/api-keys/policy-constraints") return ok(constraints);
    if (path === "/api/v1/spaces/") {
      return ok({ items: [{ id: "space-1", name: "Upphandling", applications: null }] });
    }
    if (path === "/api/v1/spaces/{id}/applications/") {
      return ok({
        assistants: { items: [{ id: "assistant-1", name: "Upphandlingsstöd" }] },
        apps: { items: [] }
      });
    }
    return Promise.resolve({ error: {}, response: new Response("{}", { status: 404 }) });
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function open(constraints: object = {}) {
  serve(constraints);
  const onCreated = vi.fn();
  const queryClient = testQueryClient();
  renderInApp(
    <CreateApiKeyDialog idPrefix="test" trigger={<Button>Skapa</Button>} onCreated={onCreated} />,
    { queryClient, appContext: testAppContext({ permissions: ["api_keys"] }) }
  );
  fireEvent.click(screen.getByRole("button", { name: "Skapa" }));
  const dialog = await screen.findByRole("dialog", { name: "Skapa API-nyckel" });
  await within(dialog).findByLabelText("Namn");
  return { dialog, onCreated, queryClient };
}

async function addToken(input: HTMLElement, value: string) {
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value } });
  await act(async () => {});
  fireEvent.keyDown(input, { key: "Enter" });
  await act(async () => {});
}

describe("CreateApiKeyDialog", () => {
  it("creates a public key with its allowed origins and hands over the secret once", async () => {
    api.POST.mockReturnValue(
      ok({ api_key: { id: "key-1", name: "Webbwidget" }, secret: "pk_live_secret_value" })
    );
    const { dialog, onCreated, queryClient } = await open();
    fireEvent.change(within(dialog).getByLabelText("Namn"), { target: { value: "Webbwidget" } });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Publik nyckel" }));

    // A public key without origins says so at the field, which takes focus.
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa" }));
    const origins = within(dialog).getByRole("combobox", { name: /Tillåtna ursprung/ });
    expect(document.activeElement).toBe(origins);
    expect(origins.getAttribute("aria-invalid")).toBe("true");
    expect(within(dialog).getByText(/Minst ett tillåtet ursprung krävs/)).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();

    await addToken(origins, "https://sundsvall.se");
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("pk_live_secret_value"));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/api-keys", {
      body: expect.objectContaining({
        name: "Webbwidget",
        key_type: "pk_",
        permission: "read",
        allowed_origins: ["https://sundsvall.se"],
        allowed_ips: null
      })
    });
    // The secret is nowhere in React Query's cache.
    const cached = JSON.stringify(
      queryClient
        .getMutationCache()
        .getAll()
        .map((mutation) => mutation.state)
    );
    expect(cached).not.toContain("pk_live_secret_value");
  });

  it("flags an invalid allowed IP as soon as it is added", async () => {
    const { dialog } = await open();
    const ips = within(dialog).getByRole("combobox", { name: /Tillåtna IP-adresser/ });
    await addToken(ips, "300.1.1.1");
    expect(ips.getAttribute("aria-invalid")).toBe("true");
    expect(within(dialog).getByText(/300\.1\.1\.1: /)).toBeTruthy();
  });

  it("does not drop an IP that is typed but not added", async () => {
    const { dialog } = await open();
    fireEvent.change(within(dialog).getByLabelText("Namn"), { target: { value: "Integration" } });
    const ips = within(dialog).getByRole("combobox", { name: /Tillåtna IP-adresser/ });
    fireEvent.change(ips, { target: { value: "203.0.113.5" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa" }));

    expect(api.POST).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(ips);
    expect(within(dialog).getByText(/203\.0\.113\.5.* är inte tillagd än/)).toBeTruthy();
  });

  it("still stops on typed text after a token is removed or the key type changes", async () => {
    const { dialog } = await open();
    fireEvent.change(within(dialog).getByLabelText("Namn"), { target: { value: "Integration" } });
    const ips = within(dialog).getByRole("combobox", { name: /Tillåtna IP-adresser/ });
    await addToken(ips, "203.0.113.5");
    fireEvent.change(ips, { target: { value: "198.51.100.2" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /203\.0\.113\.5/ }));
    expect(ips).toHaveProperty("value", "198.51.100.2");
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa" }));
    expect(api.POST).not.toHaveBeenCalled();

    // Switching the key type clears the field together with its check.
    fireEvent.click(within(dialog).getByRole("radio", { name: "Publik nyckel" }));
    fireEvent.click(within(dialog).getByRole("radio", { name: "Hemlig nyckel" }));
    const fresh = within(dialog).getByRole("combobox", { name: /Tillåtna IP-adresser/ });
    expect(fresh).toHaveProperty("value", "");
  });

  it("keeps a one-day policy's expiry within the backend's limit", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-28T09:00:00Z"));
    try {
      api.POST.mockReturnValue(ok({ api_key: { id: "key-1" }, secret: "sk_secret" }));
      const { dialog } = await open({ require_expiration: true, max_expiration_days: 1 });
      fireEvent.change(within(dialog).getByLabelText("Namn"), { target: { value: "Kort" } });
      fireEvent.click(within(dialog).getByRole("radio", { name: "Anpassad" }));
      fireEvent.click(within(dialog).getByRole("button", { name: "Skapa" }));

      await waitFor(() => expect(api.POST).toHaveBeenCalled());
      const body = api.POST.mock.calls[0]?.[1]?.body as { expires_at: string };
      expect(new Date(body.expires_at).getTime()).toBeLessThanOrEqual(
        new Date("2026-10-29T09:00:00Z").getTime()
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers the spaces while the assistants and apps are still loading", async () => {
    const { dialog } = await open();
    api.GET.mockImplementation((path: string) =>
      path === "/api/v1/spaces/{id}/applications/"
        ? new Promise(() => {})
        : path === "/api/v1/spaces/"
          ? ok({ items: [{ id: "space-1", name: "Upphandling", applications: null }] })
          : Promise.resolve({ error: {}, response: new Response("{}", { status: 404 }) })
    );
    fireEvent.click(within(dialog).getByRole("radio", { name: "Yta" }));
    const picker = await within(dialog).findByRole("combobox", { name: "Välj yta" });
    await waitFor(() => expect(picker.hasAttribute("disabled")).toBe(false));
    expect(api.GET).not.toHaveBeenCalledWith(
      "/api/v1/spaces/{id}/applications/",
      expect.anything()
    );
  });

  it("follows the policy: required and bounded expiry, capped rate limit", async () => {
    const { dialog } = await open({
      require_expiration: true,
      max_expiration_days: 60,
      max_rate_limit: 500
    });
    const expiry = within(dialog).getByRole("radiogroup", { name: "Utgångsdatum" });
    // Presets beyond 60 days and "no expiry" are not offered.
    expect(within(expiry).getByRole("radio", { name: "30 dagar" })).toBeTruthy();
    expect(within(expiry).queryByRole("radio", { name: "90 dagar" })).toBeNull();
    expect(within(expiry).queryByRole("radio", { name: "Inget utgångsdatum" })).toBeNull();

    fireEvent.change(within(dialog).getByLabelText("Namn"), { target: { value: "Integration" } });
    fireEvent.change(within(dialog).getByLabelText(/Anropsgräns/), { target: { value: "800" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa" }));
    expect(
      within(dialog).getByText("Maximalt tillåtet: 500 förfrågningar per timme.", {
        selector: "[id$='-problem'] *, [id$='-problem']"
      })
    ).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("scopes a key to a picked assistant, with the assistant's access", async () => {
    api.POST.mockReturnValue(ok({ api_key: { id: "key-1" }, secret: "sk_secret" }));
    const { dialog } = await open();
    fireEvent.change(within(dialog).getByLabelText("Namn"), {
      target: { value: "Assistentnyckel" }
    });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Assistent" }));

    // Without a picked assistant, the picker says so.
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa" }));
    expect(within(dialog).getByText("Vänligen välj en assistent eller ange dess ID")).toBeTruthy();

    fireEvent.change(within(dialog).getByLabelText("Eller ange assistent-ID manuellt"), {
      target: { value: "assistant-1" }
    });
    expect(within(dialog).getByRole("combobox", { name: "Konversationer" })).toBeTruthy();
    expect(within(dialog).queryByRole("combobox", { name: "Kunskap" })).toBeNull();
    await expectNoAxeViolations(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/api-keys", {
        body: expect.objectContaining({
          scope_type: "assistant",
          scope_id: "assistant-1",
          resource_permissions: expect.objectContaining({ assistants: "read", knowledge: "none" })
        })
      })
    );
  });
});
