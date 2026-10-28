import type { components } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

type TenantSharePointAppPublic = components["schemas"]["TenantSharePointAppPublic"];
type SharePointSubscription = components["schemas"]["SharePointSubscriptionPublic"];

const api = vi.hoisted(() => ({
  client: { fetch: vi.fn() },
  integrations: {
    admin: {
      sharepoint: {
        listSubscriptions: vi.fn<() => Promise<SharePointSubscription[]>>(async () => []),
        renewExpiredSubscriptions: vi.fn(),
        testStoredConnection: vi.fn(async () => ({ success: true })),
        restartServiceAccountAuth: vi.fn(async () => ({
          auth_url: "https://login.microsoftonline.com/authorize",
          state: "state-123"
        }))
      }
    }
  }
}));
const followServiceAccountSignIn = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({ getEneo: () => api }));
vi.mock("$lib/features/integrations/sharepoint/serviceAccountAuth", () => ({
  SHAREPOINT_SERVICE_ACCOUNT_OAUTH_KEY: "sharepoint_service_account_oauth",
  followServiceAccountSignIn
}));
vi.mock("$app/navigation", () => ({
  goto: vi.fn(),
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  onNavigate: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  preloadData: vi.fn(),
  preloadCode: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn(),
  disableScrollHandling: vi.fn()
}));
vi.mock("$app/stores", async () => {
  const { writable } = await import("svelte/store");
  return { page: writable({ url: new URL("http://localhost/admin/integrations"), state: {} }) };
});

import AdminIntegrationsPage from "./+page.svelte";

function config(overrides: Partial<TenantSharePointAppPublic> = {}): TenantSharePointAppPublic {
  return {
    id: "app-1",
    tenant_id: "tenant-1",
    client_id: "12345678-1234-1234-1234-123456789012",
    client_secret_masked: "********xyz",
    tenant_domain: "kommunen.onmicrosoft.com",
    is_active: true,
    auth_method: "service_account",
    service_account_email: "eneo@kommunen.onmicrosoft.com",
    certificate_path: null,
    auth_status: "ok",
    last_auth_error: null,
    last_auth_error_at: null,
    last_auth_success_at: "2026-10-12T08:00:00Z",
    created_by: null,
    created_at: "2026-08-01T09:00:00Z",
    updated_at: "2026-10-12T08:00:00Z",
    ...overrides
  };
}

function show(app: TenantSharePointAppPublic | null) {
  api.client.fetch.mockReset().mockImplementation(async (path: string) => {
    if (path === "/api/v1/admin/sharepoint/app") return app;
    throw new Error(`Unexpected call: ${path}`);
  });
  api.integrations.admin.sharepoint.restartServiceAccountAuth.mockClear();
  api.integrations.admin.sharepoint.listSubscriptions.mockReset().mockResolvedValue([]);
  followServiceAccountSignIn.mockClear();
  return render(AdminIntegrationsPage, {
    data: {
      eneo: api,
      tenantIntegrations: [
        {
          integration_id: "sharepoint",
          name: "SharePoint",
          description: "",
          integration_type: "sharepoint"
        }
      ],
      settings: { sharepoint_fixture_mode_available: false }
    }
  } as never);
}

describe("admin integrations page: SharePoint credential health", () => {
  it("explains a credential failure and restarts the sign-in without touching the app", async () => {
    show(
      config({
        auth_status: "error",
        last_auth_error:
          "AADSTS7000215: Invalid client secret provided. Ensure the secret being sent in the request is the client secret value, not the client secret ID.",
        last_auth_error_at: "2026-10-13T06:30:00Z"
      })
    );

    await expect.element(page.getByText(m.sharepoint_auth_status_error())).toBeVisible();
    await expect.element(page.getByText(m.sharepoint_auth_guidance_invalid_client())).toBeVisible();
    await expect.element(page.getByText(m.sharepoint_auth_error_details())).toBeVisible();
    // The raw Microsoft text stays available behind the disclosure.
    expect(page.getByText(/AADSTS7000215/).query()).not.toBeNull();

    await page.getByRole("button", { name: m.sharepoint_reauth_with_microsoft() }).click();

    expect(api.integrations.admin.sharepoint.restartServiceAccountAuth).toHaveBeenCalledOnce();
    expect(followServiceAccountSignIn).toHaveBeenCalledWith({
      auth_url: "https://login.microsoftonline.com/authorize",
      state: "state-123"
    });
    // No delete and no re-create: the app and its knowledge stay.
    expect(
      api.client.fetch.mock.calls.filter(
        ([, init]) => (init as { method: string }).method !== "get"
      )
    ).toHaveLength(0);
  });

  it("shows verified credentials and keeps the sign-in restart for the configuration dialog", async () => {
    show(config());

    await expect.element(page.getByText(m.sharepoint_auth_status_ok())).toBeVisible();
    expect(
      page.getByRole("button", { name: m.sharepoint_reauth_with_microsoft() }).query()
    ).toBeNull();

    await page.getByRole("button", { name: m.update_configuration() }).click();
    await expect.element(page.getByText(m.current_configuration())).toBeVisible();
    await page.getByRole("button", { name: m.sharepoint_reauth_with_microsoft() }).click();

    expect(api.integrations.admin.sharepoint.restartServiceAccountAuth).toHaveBeenCalledOnce();
    expect(followServiceAccountSignIn).toHaveBeenCalledOnce();
  });

  it("offers no sign-in restart for a tenant app", async () => {
    show(
      config({
        auth_method: "tenant_app",
        service_account_email: null,
        auth_status: "error",
        last_auth_error: "invalid_client"
      })
    );

    await expect.element(page.getByText(m.sharepoint_auth_status_error())).toBeVisible();
    expect(
      page.getByRole("button", { name: m.sharepoint_reauth_with_microsoft() }).query()
    ).toBeNull();
  });

  it("keeps a connection test result on screen while the stored config reloads", async () => {
    show(config());
    const appFetches = () =>
      api.client.fetch.mock.calls.filter(([path]) => path === "/api/v1/admin/sharepoint/app")
        .length;
    const runTest = page.getByRole("button", { name: m.sharepoint_health_test_run() });
    await expect.element(runTest).toBeVisible();
    const before = appFetches();

    await runTest.click();

    await expect.element(page.getByText(m.sharepoint_health_test_ok())).toBeVisible();
    // The test records credential health, so the config is fetched again.
    expect(appFetches()).toBe(before + 1);
  });

  it("shows a renewal from the watch list in the connection health as well", async () => {
    let renewed = false;
    const watch = (): SharePointSubscription =>
      ({
        id: "sub-1",
        site_id: "site-1",
        drive_id: "drive-1",
        expires_at: "2026-10-20T00:00:00Z",
        created_at: "2026-10-01T00:00:00Z",
        expires_in_hours: renewed ? 100 : 0,
        is_expired: !renewed,
        owner_type: "organization",
        owner_email: null,
        last_webhook_received_at: null,
        consecutive_renewal_failures: 0
      }) as SharePointSubscription;
    show(config());
    const sharepoint = api.integrations.admin.sharepoint;
    sharepoint.listSubscriptions.mockImplementation(async () => [watch()]);
    sharepoint.renewExpiredSubscriptions.mockImplementation(async () => {
      renewed = true;
      return { total_subscriptions: 1, expired_count: 1, recreated: 1, failed: 0, errors: [] };
    });

    await expect
      .element(
        page.getByText(
          m.sharepoint_health_watch_issues_expired({ active: 0, total: 1, expired: 1 })
        )
      )
      .toBeVisible();
    await page.getByRole("button", { name: m.sharepoint_health_watch_show() }).click();
    await page
      .getByRole("button", { name: m.sharepoint_subscriptions_renew_all_expired({ count: 1 }) })
      .click();

    await expect.element(page.getByText(m.sharepoint_health_watch_ok_one())).toBeVisible();
    expect(
      page.getByRole("button", { name: m.sharepoint_health_watch_renew() }).query()
    ).toBeNull();
  });
});
