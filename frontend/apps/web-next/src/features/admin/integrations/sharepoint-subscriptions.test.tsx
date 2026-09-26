// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
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

afterEach(cleanup);

describe("SharePointSubscriptions", () => {
  it("names the subscription table by its title", async () => {
    const { container } = renderInApp(<SharePointSubscriptions />);

    const table = await screen.findByRole("table", { name: "SharePoint Webhook-prenumerationer" });
    expect(within(table).getByText("anna.lind@example.se")).toBeTruthy();
    await expectNoAxeViolations(container);
  });
});
