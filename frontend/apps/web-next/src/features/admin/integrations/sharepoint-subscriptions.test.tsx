// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    POST: post,
    GET: () =>
      Promise.resolve({
        data: [
          {
            id: "sub-1",
            owner_type: "user",
            owner_email: "anna.lind@example.se",
            site_id: "site-0123456789abcdef",
            expires_at: "2026-10-01T08:00:00Z",
            expires_in_hours: 120,
            is_expired: false,
            consecutive_renewal_failures: 0
          }
        ],
        response: new Response("{}")
      })
  }
}));

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
});
