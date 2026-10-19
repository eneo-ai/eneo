// @vitest-environment jsdom
import { useQuery } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

import { browserApi } from "@/lib/api/browser";
import { type ModelProvider, modelProvidersQueryOptions, PROVIDERS_KEY } from "./model-providers";
import { ProviderConnectionStatus } from "./provider-connection-status";

const CHECK_PATH = "/api/v1/admin/model-providers/{provider_id}/connection-check/";

function provider(overrides: Partial<ModelProvider> = {}): ModelProvider {
  return {
    id: "p-openai",
    tenant_id: "t",
    name: "OpenAI",
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

/** The card's data flow: the line reads the provider from the providers query. */
function Line({ id }: { id: string }) {
  const { data } = useQuery(modelProvidersQueryOptions(browserApi));
  const current = data?.find((item) => item.id === id);
  return current ? <ProviderConnectionStatus provider={current} /> : null;
}

function renderLine(initial: ModelProvider) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(PROVIDERS_KEY, [initial]);
  renderInApp(<Line id={initial.id} />, { queryClient });
}

function politeAnnouncement() {
  return document.querySelector("[data-astryx-live-region='polite']")?.textContent;
}

function testButton() {
  return screen.getByRole("button", { name: "Testa anslutning till OpenAI" });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("ProviderConnectionStatus", () => {
  it("shows an untested provider with a test button", async () => {
    renderLine(provider());

    expect(screen.getByText("Inte testad")).toBeTruthy();
    expect(testButton().textContent).toContain("Testa anslutning");
    await expectNoAxeViolations(document.body);
  });

  it("shows a working connection and when it was checked", async () => {
    renderLine(
      provider({
        connection_check: { status: "ok", checked_at: new Date().toISOString(), error: null }
      })
    );

    expect(screen.getByText("Anslutningen fungerar")).toBeTruthy();
    expect(screen.getByText(/^Kontrollerad/).querySelector("time")).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("shows a failed connection with its reason in text, not only colour", async () => {
    renderLine(
      provider({
        connection_check: {
          status: "failed",
          checked_at: "2026-09-26T08:00:00Z",
          error: "authentication_failed"
        }
      })
    );

    expect(screen.getByText("Anslutningen misslyckades: API-nyckeln godkändes inte")).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("names a reason it does not know as an unknown error", () => {
    renderLine(
      provider({
        connection_check: {
          status: "failed",
          checked_at: "2026-09-26T08:00:00Z",
          error: "a_future_reason" as never
        }
      })
    );

    expect(screen.getByText("Anslutningen misslyckades: okänt fel")).toBeTruthy();
  });

  it("offers no test for a provider type that has none", () => {
    renderLine(provider({ connection_check_supported: false }));

    expect(
      screen.getByText("Anslutningen kan inte testas för den här leverantörstypen")
    ).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("tests the connection, announces that it works and shows the result", async () => {
    let finish: (value: unknown) => void = () => {};
    api.POST.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    renderLine(provider());
    const button = testButton();
    button.focus();

    fireEvent.click(button);

    await waitFor(() => expect(button.getAttribute("aria-busy")).toBe("true"));
    // Busy, but still enabled so keyboard focus stays; a second press is ignored.
    expect(button.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(api.POST).toHaveBeenCalledWith(CHECK_PATH, {
      params: { path: { provider_id: "p-openai" } }
    });

    await act(async () =>
      finish({
        data: provider({
          connection_check: { status: "ok", checked_at: new Date().toISOString(), error: null }
        }),
        response: new Response("{}")
      })
    );

    expect(await screen.findByText("Anslutningen fungerar")).toBeTruthy();
    await waitFor(() => expect(politeAnnouncement()).toBe("Anslutningen till OpenAI fungerar"));
    expect(toast.error).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(testButton());
    expect(testButton().getAttribute("aria-busy")).toBeNull();
  });

  it("reports a failed check once, in a toast that stays", async () => {
    api.POST.mockResolvedValue({
      data: provider({
        connection_check: {
          status: "failed",
          checked_at: new Date().toISOString(),
          error: "timeout"
        }
      }),
      response: new Response("{}")
    });
    renderLine(provider());

    fireEvent.click(testButton());

    expect(await screen.findByText("Anslutningen misslyckades: inget svar i tid")).toBeTruthy();
    expect(toast.error).toHaveBeenCalledWith(
      "Anslutningen till OpenAI misslyckades: inget svar i tid"
    );
    // Not also through the live region: that would read it twice.
    expect(politeAnnouncement() ?? "").not.toContain("misslyckades");
  });

  it("keeps the last result and shows the error when the check cannot run", async () => {
    api.POST.mockResolvedValue({
      error: { message: "Service unavailable" },
      response: new Response("{}", { status: 503 })
    });
    renderLine(provider());

    fireEvent.click(testButton());

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(toast.error.mock.calls[0]?.[0]).toBe("Service unavailable");
    expect(screen.getByText("Inte testad")).toBeTruthy();
    await waitFor(() => expect(testButton().getAttribute("aria-busy")).toBeNull());
  });
});

describe("key expiry notice", () => {
  // Only Date is faked: React Query and Astryx keep their real timers.
  function today(date: Date) {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(date);
  }

  it("says nothing more than 30 days ahead", () => {
    today(new Date(2026, 8, 26, 10));
    renderLine(provider({ key_expires_on: "2026-10-27" }));

    expect(screen.queryByText(/Nyckeln/)).toBeNull();
  });

  it("warns from 30 days before the expiry date through that day", async () => {
    today(new Date(2026, 8, 26, 10));
    renderLine(provider({ key_expires_on: "2026-10-26" }));

    expect(screen.getByText("Nyckeln går ut 26 okt.")).toBeTruthy();
    await expectNoAxeViolations(document.body);
    cleanup();

    today(new Date(2026, 9, 26, 23, 30));
    renderLine(provider({ key_expires_on: "2026-10-26" }));
    expect(screen.getByText("Nyckeln går ut 26 okt.")).toBeTruthy();
  });

  it("is an error from the day after", async () => {
    today(new Date(2026, 9, 4, 8));
    renderLine(provider({ key_expires_on: "2026-10-03" }));

    expect(screen.getByText("Nyckeln har gått ut 3 okt.")).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("names the year when it is not this one", () => {
    today(new Date(2026, 11, 20, 10));
    renderLine(provider({ key_expires_on: "2027-01-12" }));

    expect(screen.getByText("Nyckeln går ut 12 jan. 2027")).toBeTruthy();
  });
});
