// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  toast: { success: vi.fn(), info: vi.fn(), warning: vi.fn(), error: vi.fn() }
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast: spies.toast }));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));

import { SharePointConnectionHealth, worstHealth } from "./sharepoint-connection-health";

type App = Schema<"TenantSharePointAppPublic">;
type Subscription = Schema<"SharePointSubscriptionPublic">;

function app(overrides: Partial<App> = {}): App {
  return {
    id: "app-1",
    tenant_id: "tenant-1",
    client_id: "11111111-2222-3333-4444-55556666abcd",
    client_secret_masked: "********wxyz",
    tenant_domain: "sundsvall.onmicrosoft.com",
    is_active: true,
    auth_method: "tenant_app",
    certificate_path: null,
    auth_status: "ok",
    last_auth_success_at: "2026-10-13T08:00:00Z",
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-13T08:00:00Z",
    ...overrides
  };
}

let nextId = 0;
function subscription(overrides: Partial<Subscription> = {}): Subscription {
  nextId += 1;
  return {
    id: `sub-${nextId}`,
    user_integration_id: "ui-1",
    site_id: "site-0123456789abcdef",
    subscription_id: `graph-${nextId}`,
    drive_id: "drive-1",
    expires_at: "2026-11-01T08:00:00Z",
    created_at: "2026-10-01T08:00:00Z",
    is_expired: false,
    expires_in_hours: 400,
    owner_type: "organization",
    consecutive_renewal_failures: 0,
    ...overrides
  };
}

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

let subscriptions: Subscription[] = [];

function respond(posts: Record<string, unknown> = {}) {
  api.GET.mockImplementation((path: string) =>
    path === "/api/v1/admin/sharepoint/subscriptions" ? ok(subscriptions) : ok(null)
  );
  api.POST.mockImplementation((path: string) => ok(posts[path] ?? null));
}

function show(config: App) {
  const onEdit = vi.fn();
  const view = renderInApp(<SharePointConnectionHealth config={config} onEdit={onEdit} />);
  const health = screen.getByRole("region", { name: "Anslutningens hälsa" });
  return { onEdit, health, container: view.container };
}

beforeEach(() => {
  subscriptions = [];
  respond();
  sessionStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("worstHealth", () => {
  it("sums up the checks by the most severe", () => {
    expect(worstHealth(["ok", "ok"])).toBe("ok");
    expect(worstHealth(["ok", "unknown"])).toBe("unknown");
    expect(worstHealth(["unknown", "warning"])).toBe("warning");
    expect(worstHealth(["warning", "error", "ok"])).toBe("error");
  });
});

describe("SharePointConnectionHealth", () => {
  it("says everything works, and runs and records a passing connection test", async () => {
    subscriptions = [subscription()];
    respond({ "/api/v1/admin/sharepoint/app/test": { success: true } });
    const { health, container } = show(app());

    expect(
      await within(health).findByText(
        "1 bevakningar aktiva. Nya och ändrade filer hämtas inom några minuter."
      )
    ).toBeTruthy();
    expect(within(health).getByText("Allt fungerar")).toBeTruthy();
    expect(
      within(health).getByText("sundsvall.onmicrosoft.com · klient-id som slutar på abcd")
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(within(health).getByRole("button", { name: "Kör test" }));

    expect(await within(health).findByText("Anslutningen fungerar.")).toBeTruthy();
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/sharepoint/app/test");
    expect(spies.announce).toHaveBeenCalledWith("Anslutningen fungerar.");
  });

  it("shows why a connection test failed and announces it", async () => {
    respond({
      "/api/v1/admin/sharepoint/app/test": {
        success: false,
        error_message: "AADSTS7000215: Invalid client secret provided."
      }
    });
    const { health } = show(app());

    fireEvent.click(within(health).getByRole("button", { name: "Kör test" }));

    expect(
      await within(health).findByText("AADSTS7000215: Invalid client secret provided.")
    ).toBeTruthy();
    expect(spies.announce).toHaveBeenCalledWith("AADSTS7000215: Invalid client secret provided.");
  });

  it("restarts a refused service-account sign-in with Microsoft", async () => {
    const authUrl = `${window.location.origin}/#microsoft-sign-in`;
    respond({
      "/api/v1/admin/sharepoint/service-account/auth/reauth": { auth_url: authUrl, state: "s-1" }
    });
    const { health, onEdit, container } = show(
      app({
        auth_method: "service_account",
        service_account_email: "eneo-sync@sundsvall.se",
        auth_status: "error",
        last_auth_error: "AADSTS700082: The refresh token has expired",
        last_auth_error_at: "2026-10-14T21:01:00Z"
      })
    );

    expect(within(health).getByText("Kräver åtgärd")).toBeTruthy();
    expect(
      within(health).getByText(
        "Ingen kunskap från SharePoint uppdateras förrän detta är åtgärdat. Dokument som redan är importerade går fortfarande att söka i."
      )
    ).toBeTruthy();
    expect(within(health).getByText("Loggar in som eneo-sync@sundsvall.se")).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(within(health).getByRole("button", { name: "Logga in igen med Microsoft" }));

    await waitFor(() => expect(window.location.hash).toBe("#microsoft-sign-in"));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/sharepoint/service-account/auth/reauth", {
      body: { redirect_uri: `${window.location.origin}/integrations/callback/token/` }
    });
    expect(JSON.parse(sessionStorage.getItem("sharepoint_service_account_oauth") ?? "{}")).toEqual({
      state: "s-1"
    });
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("sends a refused tenant-app sign-in to the configuration, with the guidance that fits", () => {
    const { health, onEdit } = show(
      app({
        auth_status: "error",
        last_auth_error: "invalid_client: AADSTS7000215 Invalid client secret provided."
      })
    );

    expect(
      within(health).getByText(
        "Klienthemligheten är fel eller har gått ut. Skapa en ny hemlighet i Entra ID och ange dess värde, inte dess ID."
      )
    ).toBeTruthy();
    expect(
      within(health).queryByRole("button", { name: "Logga in igen med Microsoft" })
    ).toBeNull();

    fireEvent.click(within(health).getByRole("button", { name: "Uppdatera konfiguration" }));

    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("counts lapsed watches, renews the expired ones and shows the watches on request", async () => {
    subscriptions = [
      subscription(),
      subscription({ is_expired: true }),
      subscription({ consecutive_renewal_failures: 2 })
    ];
    respond({
      "/api/v1/admin/sharepoint/subscriptions/renew-expired": { recreated: 1, failed: 0 }
    });
    const { health } = show(app());

    expect(
      await within(health).findByText(
        "1 av 3 bevakningar aktiva: 1 har gått ut och 1 kunde inte förnyas. De mapparna uppdateras bara vid fullständig synk."
      )
    ).toBeTruthy();
    expect(within(health).getByText("Behöver ses över")).toBeTruthy();

    fireEvent.click(within(health).getByRole("button", { name: "Förnya utgångna" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/sharepoint/subscriptions/renew-expired")
    );
    await waitFor(() => expect(spies.toast.success).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        api.GET.mock.calls.filter(([path]) => path === "/api/v1/admin/sharepoint/subscriptions")
      ).toHaveLength(2)
    );

    const show_ = within(health).getByRole("button", { name: "Visa bevakningar" });
    expect(show_.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(show_);

    const hide = within(health).getByRole("button", { name: "Dölj bevakningar" });
    expect(hide.getAttribute("aria-expanded")).toBe("true");
    expect(
      await screen.findByRole("table", { name: "SharePoint Webhook-prenumerationer" })
    ).toBeTruthy();
  });

  it("moves focus to the watches button once the renewed ones are no longer expired", async () => {
    subscriptions = [subscription(), subscription({ is_expired: true })];
    respond({
      "/api/v1/admin/sharepoint/subscriptions/renew-expired": { recreated: 1, failed: 0 }
    });
    const { health } = show(app());
    const renew = await within(health).findByRole("button", { name: "Förnya utgångna" });

    // The refetch after the renewal finds nothing expired, so the button goes.
    subscriptions = [subscription(), subscription()];
    renew.focus();
    fireEvent.click(renew);

    await waitFor(() =>
      expect(within(health).queryByRole("button", { name: "Förnya utgångna" })).toBeNull()
    );
    await waitFor(
      () =>
        expect(document.activeElement).toBe(
          within(health).getByRole("button", { name: "Visa bevakningar" })
        ),
      { timeout: 1500 }
    );
  });
});
