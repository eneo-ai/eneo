// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { NextIntlClientProvider } from "next-intl";
import en from "@/lib/i18n/messages/en.json";
import { renderInApp } from "@/test/render";

const post = vi.hoisted(() => vi.fn());
const listed = vi.hoisted(() => ({ subscriptions: [] as Record<string, unknown>[] }));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    POST: post,
    GET: () => Promise.resolve({ data: listed.subscriptions, response: new Response("{}") })
  }
}));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/toast", () => ({ toast }));

const subscription = (overrides: Record<string, unknown> = {}) => ({
  id: "sub-1",
  owner_type: "user",
  owner_email: "anna.lind@example.se",
  site_id: "site-0123456789abcdef",
  expires_at: "2026-10-01T08:00:00Z",
  expires_in_hours: 120,
  is_expired: false,
  consecutive_renewal_failures: 0,
  ...overrides
});

beforeEach(() => {
  listed.subscriptions = [subscription()];
});

import { SharePointSubscriptions } from "./sharepoint-subscriptions";

afterEach(() => {
  cleanup();
  post.mockReset();
});

describe("SharePointSubscriptions", () => {
  it("names the subscription table by its title", async () => {
    const { container } = renderInApp(<SharePointSubscriptions />);

    const table = await screen.findByRole("table", { name: "SharePoint Webhook-prenumerationer" });
    expect(within(table).getByText("anna.lind@example.se")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("keeps focus on a busy Förnya and renews once", async () => {
    post.mockReturnValue(new Promise(() => {}));
    renderInApp(<SharePointSubscriptions />);
    const renew = await screen.findByRole("button", { name: "Förnya" });
    renew.focus();

    fireEvent.click(renew);

    const busy = await screen.findByRole("button", { name: "Förnyar..." });
    expect(busy).toBe(renew);
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(busy.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(busy);
    fireEvent.click(busy);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("moves focus to the title once Renew all expired goes with the renewed watches", async () => {
    listed.subscriptions = [subscription({ is_expired: true, expires_in_hours: -5 })];
    post.mockResolvedValue({ data: { recreated: 1, failed: 0 }, response: new Response("{}") });
    renderInApp(<SharePointSubscriptions />);
    const renewAll = await screen.findByRole("button", { name: "Förnya alla utgångna (1)" });

    // The refetch after the renewal finds nothing expired, so the button goes.
    listed.subscriptions = [subscription()];
    renewAll.focus();
    fireEvent.click(renewAll);

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Förnya alla utgångna (1)" })).toBeNull()
    );
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByText("SharePoint Webhook-prenumerationer"))
    );
    expect(toast.success).toHaveBeenCalledWith("1 prenumeration förnyad");
  });

  it("shows a renewal error in full, without a hover tooltip", async () => {
    const error =
      "Subscription validation request failed. Notification endpoint must respond with 200 OK.";
    listed.subscriptions = [
      subscription({ consecutive_renewal_failures: 2, last_renewal_error: error })
    ];
    renderInApp(<SharePointSubscriptions />);

    const shown = await screen.findByText(error);
    expect(shown.getAttribute("title")).toBeNull();
    expect(shown.className).not.toContain("truncate");
  });

  it("counts one renewal failure in the singular", async () => {
    listed.subscriptions = [subscription({ consecutive_renewal_failures: 1 })];
    // Swedish says "1 förnyelsefel" either way; English tells the forms apart.
    renderInApp(
      <NextIntlClientProvider locale="en" messages={en} timeZone="Europe/Stockholm">
        <SharePointSubscriptions />
      </NextIntlClientProvider>
    );
    expect(await screen.findByText("1 renewal failure")).toBeTruthy();
  });
});
