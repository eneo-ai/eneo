import type { Eneo, components } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import "../../../../app.css";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
import SharePointConnectionHealth from "./SharePointConnectionHealth.svelte";
import { SharePointSubscriptionList } from "./SharePointSubscriptionList.svelte";

type App = components["schemas"]["TenantSharePointAppPublic"];
type Subscription = components["schemas"]["SharePointSubscriptionPublic"];

function app(overrides: Partial<App> = {}): App {
  return {
    id: "app-1",
    tenant_id: "t-1",
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
  } as App;
}

function subscription(overrides: Partial<Subscription>): Subscription {
  return {
    id: crypto.randomUUID(),
    is_expired: false,
    consecutive_renewal_failures: 0,
    ...overrides
  } as Subscription;
}

function show(config: App, subscriptions: Subscription[] = []) {
  const sharepoint = {
    listSubscriptions: vi.fn().mockResolvedValue(subscriptions),
    renewExpiredSubscriptions: vi.fn().mockResolvedValue({ recreated: 1, failed: 0 }),
    testStoredConnection: vi.fn().mockResolvedValue({ success: true }),
    restartServiceAccountAuth: vi.fn()
  };
  const eneo = { integrations: { admin: { sharepoint } } } as unknown as Eneo;
  const props = {
    eneo,
    config,
    subscriptionList: new SharePointSubscriptionList(eneo),
    subscriptionsOpen: false,
    onEdit: vi.fn(),
    onToggleSubscriptions: vi.fn(),
    onConfigChanged: vi.fn()
  };
  render(SharePointConnectionHealth, props);
  return { sharepoint, props };
}

describe("SharePointConnectionHealth", () => {
  it("says everything works and records a passing connection test", async () => {
    const { sharepoint, props } = show(app(), [subscription({})]);

    await expect.element(page.getByText(m.sharepoint_health_overall_ok())).toBeVisible();
    await expect.element(page.getByText(m.sharepoint_health_watch_ok_one())).toBeVisible();
    await page.getByRole("button", { name: m.sharepoint_health_test_run() }).click();

    await expect.element(page.getByText(m.sharepoint_health_test_ok())).toBeVisible();
    expect(sharepoint.testStoredConnection).toHaveBeenCalledTimes(1);
    expect(props.onConfigChanged).toHaveBeenCalledTimes(1);
    await expectNoAxeViolations();
  });

  it.each([
    ["service_account", m.sharepoint_reauth_with_microsoft()],
    ["tenant_app", m.update_configuration()]
  ])("offers the fix for a refused %s sign-in", async (authMethod, action) => {
    const { sharepoint, props } = show(
      app({
        auth_method: authMethod,
        auth_status: "error",
        last_auth_error: "AADSTS700082: The refresh token has expired",
        last_auth_error_at: "2026-10-14T21:01:00Z"
      })
    );

    await expect
      .element(page.getByText(m.sharepoint_health_state_error(), { exact: true }))
      .toBeVisible();
    await expect.element(page.getByText(m.sharepoint_health_sign_in_impact())).toBeVisible();
    await page.getByRole("button", { name: action }).click();

    if (authMethod === "service_account") {
      expect(sharepoint.restartServiceAccountAuth).toHaveBeenCalledTimes(1);
    } else {
      expect(props.onEdit).toHaveBeenCalledTimes(1);
    }
  });

  it("counts lapsed watches and renews the expired ones", async () => {
    const { sharepoint } = show(app(), [
      subscription({}),
      subscription({ is_expired: true }),
      subscription({ consecutive_renewal_failures: 2 })
    ]);

    await expect
      .element(
        page.getByText(
          m.sharepoint_health_watch_issues({ active: 1, total: 3, expired: 1, failing: 1 })
        )
      )
      .toBeVisible();
    await page.getByRole("button", { name: m.sharepoint_health_watch_renew() }).click();

    expect(sharepoint.renewExpiredSubscriptions).toHaveBeenCalledTimes(1);
    await expect.poll(() => sharepoint.listSubscriptions.mock.calls.length).toBe(2);
  });
});
