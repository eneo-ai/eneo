import type { components } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { writable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

type TenantSharePointAppPublic = components["schemas"]["TenantSharePointAppPublic"];
type TenantAppTestResult = components["schemas"]["TenantAppTestResult"];

const api = vi.hoisted(() => ({
  client: { fetch: vi.fn() },
  integrations: {
    admin: {
      sharepoint: {
        testStoredConnection: vi.fn<() => Promise<TenantAppTestResult>>(),
        restartServiceAccountAuth: vi.fn()
      }
    }
  }
}));

vi.mock("$lib/core/Eneo", () => ({ getEneo: () => api }));
vi.mock("$lib/components/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }
}));

import SharePointAppConfigDialog from "./SharePointAppConfigDialog.svelte";

function config(overrides: Partial<TenantSharePointAppPublic> = {}): TenantSharePointAppPublic {
  return {
    id: "app-1",
    tenant_id: "tenant-1",
    client_id: "12345678-1234-1234-1234-123456789012",
    client_secret_masked: "********xyz",
    tenant_domain: "kommunen.onmicrosoft.com",
    is_active: true,
    auth_method: "tenant_app",
    service_account_email: null,
    certificate_path: null,
    auth_status: "unknown",
    last_auth_error: null,
    last_auth_error_at: null,
    last_auth_success_at: null,
    created_by: null,
    created_at: "2026-08-01T09:00:00Z",
    updated_at: "2026-10-12T08:00:00Z",
    ...overrides
  };
}

/** The app as the backend returns it: `before` until the stored test ran, `after` from then on. */
function show(before: TenantSharePointAppPublic, after: TenantSharePointAppPublic) {
  let tested = false;
  api.client.fetch.mockReset().mockImplementation(async (path: string) => {
    if (path === "/api/v1/admin/sharepoint/app") return tested ? after : before;
    throw new Error(`Unexpected call: ${path}`);
  });
  api.integrations.admin.sharepoint.testStoredConnection
    .mockReset()
    .mockImplementation(async () => {
      tested = true;
      return after.auth_status === "ok"
        ? { success: true, details: "Token acquired successfully" }
        : { success: false, error_message: after.last_auth_error ?? "failed" };
    });
  render(SharePointAppConfigDialog, { openController: writable(true) });
}

function nonGetCalls() {
  return api.client.fetch.mock.calls.filter(
    ([, init]) => (init as { method: string }).method !== "get"
  );
}

describe("SharePointAppConfigDialog: testing the stored app", () => {
  it("reports a working connection and refreshes the credential badge", async () => {
    show(config(), config({ auth_status: "ok", last_auth_success_at: "2026-10-13T07:00:00Z" }));

    await expect.element(page.getByText(m.sharepoint_auth_status_unknown())).toBeVisible();
    await page.getByRole("button", { name: m.test_connection() }).click();

    await expect.element(page.getByText(m.sharepoint_stored_connection_ok())).toBeVisible();
    await expect.element(page.getByText(m.sharepoint_auth_status_ok())).toBeVisible();
    expect(api.integrations.admin.sharepoint.testStoredConnection).toHaveBeenCalledOnce();
    expect(nonGetCalls()).toHaveLength(0);
  });

  it("explains a failed test and keeps the app", async () => {
    const error =
      "AADSTS7000215: Invalid client secret provided. Ensure the secret being sent in the request is the client secret value, not the client secret ID.";
    show(
      config({ auth_method: "service_account", service_account_email: "eneo@kommunen.se" }),
      config({
        auth_method: "service_account",
        service_account_email: "eneo@kommunen.se",
        auth_status: "error",
        last_auth_error: error,
        last_auth_error_at: "2026-10-13T07:00:00Z"
      })
    );

    await page.getByRole("button", { name: m.test_connection() }).click();

    await expect.element(page.getByText(m.connection_failed())).toBeVisible();
    // Inline result and the refreshed health badge both carry the guidance.
    await vi.waitFor(() =>
      expect(page.getByText(m.sharepoint_auth_guidance_invalid_client()).all()).toHaveLength(2)
    );
    await expect.element(page.getByText(m.sharepoint_auth_status_error())).toBeVisible();
    expect(page.getByText(/AADSTS7000215/).all().length).toBeGreaterThan(0);
    // The stored app is untouched: no save, no delete, only the test itself.
    expect(api.integrations.admin.sharepoint.testStoredConnection).toHaveBeenCalledOnce();
    expect(nonGetCalls()).toHaveLength(0);
    await expect.element(page.getByText(m.current_configuration())).toBeVisible();
  });
});
