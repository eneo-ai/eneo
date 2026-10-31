// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { IntlProvider } from "use-intl";
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
  user_integration_id: "ui-1",
  subscription_id: "graph-1",
  drive_id: "drive-1",
  created_at: "2026-01-01T00:00:00Z",
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
  vi.clearAllMocks();
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

  it("confirms recreating all once and reports partial results before refreshing rows", async () => {
    let finish!: (value: unknown) => void;
    post.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    renderInApp(<SharePointSubscriptions />);
    await screen.findByRole("table");
    const trigger = screen.getByRole("button", { name: "Återskapa alla prenumerationer" });
    fireEvent.click(trigger);
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Avbryt" })
    );
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(trigger);
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Bekräfta" })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledExactlyOnceWith(
        "/api/v1/admin/sharepoint/subscriptions/recreate-all"
      )
    );
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Återskapar..." })
    );
    expect(post).toHaveBeenCalledTimes(1);
    const renew = screen.getByRole("button", { name: "Förnya" });
    expect(renew.hasAttribute("disabled")).toBe(false);
    fireEvent.click(renew);
    expect(post).toHaveBeenCalledTimes(1);
    listed.subscriptions = [];
    await act(async () => {
      finish({
        data: {
          total_subscriptions: 3,
          recreated: 2,
          failed: 1,
          errors: ["Microsoft nekade en prenumeration"]
        },
        response: new Response("{}")
      });
    });
    await waitFor(() =>
      expect(toast.warning).toHaveBeenCalledWith(
        "2 återskapade, 1 misslyckades. Fel: Microsoft nekade en prenumeration"
      )
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(screen.queryByText("anna.lind@example.se")).toBeNull();
  });

  it.each([
    {
      result: { total_subscriptions: 0, recreated: 0, failed: 0 },
      message: "Det finns inga prenumerationer att återskapa",
      kind: "info" as const
    },
    {
      result: { total_subscriptions: 1, recreated: 1, failed: 0 },
      message: "1 prenumeration återskapad",
      kind: "success" as const
    }
  ])("reports a completed recreate-all result: $message", async ({ result, message, kind }) => {
    post.mockResolvedValue({ data: result, response: new Response("{}") });
    renderInApp(<SharePointSubscriptions />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Återskapa alla prenumerationer" }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Bekräfta" })
    );
    await waitFor(() => expect(toast[kind]).toHaveBeenCalledWith(message));
  });

  it("keeps a failed recreate-all confirmation retryable and shows the API error", async () => {
    post
      .mockResolvedValueOnce({
        error: { message: "Microsoft rejected webhook" },
        response: new Response("{}", { status: 400 })
      })
      .mockResolvedValueOnce({
        data: { total_subscriptions: 1, recreated: 1, failed: 0 },
        response: new Response("{}")
      });
    renderInApp(<SharePointSubscriptions />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Återskapa alla prenumerationer" }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Bekräfta" })
    );
    await waitFor(() =>
      expect(JSON.stringify(toast.error.mock.calls)).toContain("Microsoft rejected webhook")
    );
    const retry = within(screen.getByRole("alertdialog")).getByRole("button", { name: "Bekräfta" });
    await waitFor(() => expect(retry.getAttribute("aria-busy")).toBeNull());
    fireEvent.click(retry);
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("1 prenumeration återskapad"));
    expect(post).toHaveBeenCalledTimes(2);
  });

  it("shows lifetime, webhook/failure timestamps, drive and creation for each row", async () => {
    const webhook = "2026-10-30T08:00:00Z";
    const failure = "2026-10-31T08:00:00Z";
    listed.subscriptions = [
      subscription({ last_webhook_received_at: webhook }),
      subscription({
        id: "sub-2",
        owner_email: "bob@example.se",
        expires_in_hours: 25,
        consecutive_renewal_failures: 1,
        last_renewal_failed_at: failure
      })
    ];
    renderInApp(<SharePointSubscriptions />);
    const table = await screen.findByRole("table");
    const anna = within(table).getByRole("row", { name: /anna.lind/ });
    expect(within(anna).getByText("5d kvar")).toBeTruthy();
    expect(within(anna).getByText(/drive-1/)).toBeTruthy();
    expect(anna.querySelector(`time[datetime="${new Date(webhook).toISOString()}"]`)).toBeTruthy();
    expect(anna.querySelector('time[datetime="2026-01-01T00:00:00.000Z"]')).toBeTruthy();
    const bob = within(table).getByRole("row", { name: /bob@example/ });
    expect(within(bob).getByText("1d 1h kvar")).toBeTruthy();
    expect(bob.querySelector(`time[datetime="${new Date(failure).toISOString()}"]`)).toBeTruthy();
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
    const bulk = screen.getByRole("button", { name: "Återskapa alla prenumerationer" });
    expect(bulk.hasAttribute("disabled")).toBe(false);
    expect(bulk.getAttribute("aria-busy")).toBe("true");
    bulk.focus();
    fireEvent.click(bulk);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(document.activeElement).toBe(bulk);
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
      <IntlProvider locale="en" messages={en} timeZone="Europe/Stockholm">
        <SharePointSubscriptions />
      </IntlProvider>
    );
    expect(await screen.findByText("1 renewal failure")).toBeTruthy();
  });
});
