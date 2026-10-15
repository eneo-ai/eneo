// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { ExpiringKeysNotification } from "./expiring-keys-notification";

const appContext = testAppContext({ settings: { api_key_expiry_notifications: true } });

const api = vi.hoisted(() => ({ items: [] as unknown[] }));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      const data =
        path === "/api/v1/api-keys/notification-preferences"
          ? { enabled: true, days_before_expiry: [14] }
          : path === "/api/v1/api-keys/notification-subscriptions"
            ? { items: [{ id: "s1" }] }
            : { items: api.items, counts_by_severity: { expired: 1, warning: 1 } };
      return Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
    }
  }
}));

afterEach(() => {
  cleanup();
  api.items = [];
});

const inDays = (days: number) => new Date(Date.now() + (days + 0.5) * 86_400_000).toISOString();

describe("ExpiringKeysNotification", () => {
  it("stays out of the way while no followed key expires", async () => {
    const { container } = renderInApp(<ExpiringKeysNotification />, { appContext });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(container.querySelector("button")).toBeNull();
  });

  it("lists the expiring keys in a popover with a way to manage them", async () => {
    api.items = [
      {
        id: "k1",
        name: "Integration",
        key_suffix: "a1",
        expires_at: inDays(-2),
        severity: "expired"
      },
      { id: "k2", name: "Rapporter", key_suffix: "b2", expires_at: inDays(9), severity: "warning" }
    ];
    renderInApp(<ExpiringKeysNotification />, { appContext });
    const bell = await screen.findByRole("button", { name: "API-nycklar som går ut" });
    bell.focus();
    fireEvent.click(bell);

    const panel = await screen.findByRole("dialog", { name: "API-nycklar som går ut" });
    expect(within(panel).getByText("1 utgångna, 1 går ut snart")).toBeTruthy();
    const items = within(panel).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "IntegrationHar gått ut",
      "RapporterGår ut om 9 dagar"
    ]);
    expect(
      within(panel).getByRole("link", { name: "Hantera API-nycklar" }).getAttribute("href")
    ).toBe("/account/api-keys");
    // Names wrap instead of being cut off behind a title tooltip.
    expect(within(panel).getByText("Integration").className).toContain("wrap-anywhere");
    expect(panel.querySelector("[title]")).toBeNull();
    await expectNoAxeViolations(document.body);

    fireEvent.keyDown(panel, { key: "Escape" });
    await waitFor(() => expect(bell.getAttribute("aria-expanded")).toBe("false"));
    expect(document.activeElement).toBe(bell);
  });
});
