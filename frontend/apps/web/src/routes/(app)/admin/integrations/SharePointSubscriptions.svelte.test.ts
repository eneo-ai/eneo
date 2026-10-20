import type { components } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

type SharePointSubscription = components["schemas"]["SharePointSubscriptionPublic"];
type SubscriptionRenewalResult = components["schemas"]["SubscriptionRenewalResult"];

const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warning: vi.fn()
}));
vi.mock("$lib/components/toast", () => ({ toast }));
vi.mock("$lib/core/errors", () => ({
  toastError: vi.fn(),
  getErrorMessage: (error: unknown) => String(error)
}));

import { SharePointSubscriptionList } from "$lib/features/integrations/sharepoint/SharePointSubscriptionList.svelte";
import SharePointSubscriptions from "./SharePointSubscriptions.svelte";

const api = {
  integrations: {
    admin: {
      sharepoint: {
        listSubscriptions: vi.fn<() => Promise<SharePointSubscription[]>>(),
        renewExpiredSubscriptions: vi.fn(),
        recreateSubscription: vi.fn(),
        recreateAllSubscriptions: vi.fn<() => Promise<SubscriptionRenewalResult>>()
      }
    }
  }
};

function subscription(): SharePointSubscription {
  return {
    id: "sub-1",
    user_integration_id: "ui-1",
    subscription_id: "graph-1",
    resource: "drives/d1/root",
    site_id: "site-1",
    drive_id: "d1",
    expires_at: "2026-11-01T00:00:00Z",
    created_at: "2026-10-01T00:00:00Z",
    expires_in_hours: 400,
    is_expired: false,
    owner_type: "organization",
    owner_email: null,
    last_webhook_received_at: null,
    consecutive_renewal_failures: 0,
    last_renewal_failed_at: null,
    last_renewal_error: null
  } as SharePointSubscription;
}

function result(overrides: Partial<SubscriptionRenewalResult> = {}): SubscriptionRenewalResult {
  return {
    total_subscriptions: 2,
    expired_count: 0,
    recreated: 2,
    failed: 0,
    errors: [],
    ...overrides
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.integrations.admin.sharepoint.listSubscriptions.mockResolvedValue([subscription()]);
});

async function openRecreateAllDialog() {
  render(SharePointSubscriptions, {
    eneo: api as never,
    subscriptionList: new SharePointSubscriptionList(api as never)
  });
  await expect
    .element(page.getByText(m.sharepoint_subscription_owner_organization()))
    .toBeVisible();
  await page.getByRole("button", { name: m.sharepoint_subscriptions_recreate_all() }).click();
  await expect.element(page.getByRole("alertdialog")).toBeVisible();
}

describe("SharePointSubscriptions: recreate all", () => {
  it.each([
    {
      name: "reports the recreated count",
      response: result(),
      expected: () =>
        expect(toast.success).toHaveBeenCalledWith(
          m.sharepoint_subscriptions_recreated_success({ count: 2 })
        )
    },
    {
      name: "reports failures with their errors",
      response: result({ recreated: 1, failed: 1, errors: ["Subscription sub-2: boom"] }),
      expected: () =>
        expect(toast.error).toHaveBeenCalledWith(
          m.sharepoint_subscriptions_recreated_partial({
            recreated: 1,
            failed: 1,
            errors: "Subscription sub-2: boom"
          })
        )
    },
    {
      name: "says when there was nothing to recreate",
      response: result({ total_subscriptions: 0, recreated: 0 }),
      expected: () =>
        expect(toast.info).toHaveBeenCalledWith(m.sharepoint_subscriptions_none_to_recreate())
    }
  ])("confirming recreates every subscription and $name", async ({ response, expected }) => {
    api.integrations.admin.sharepoint.recreateAllSubscriptions.mockResolvedValue(response);
    await openRecreateAllDialog();
    await expect
      .element(page.getByText(m.sharepoint_subscriptions_recreate_all_description()))
      .toBeVisible();

    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: m.sharepoint_subscriptions_recreate_all() })
      .click();

    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.integrations.admin.sharepoint.recreateAllSubscriptions).toHaveBeenCalledOnce();
    expected();
    // The table is reloaded after the recreation.
    expect(api.integrations.admin.sharepoint.listSubscriptions).toHaveBeenCalledTimes(2);
  });

  it("cancelling makes no call", async () => {
    await openRecreateAllDialog();

    await page.getByRole("button", { name: m.cancel() }).click();

    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.integrations.admin.sharepoint.recreateAllSubscriptions).not.toHaveBeenCalled();
    expect(api.integrations.admin.sharepoint.renewExpiredSubscriptions).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});
