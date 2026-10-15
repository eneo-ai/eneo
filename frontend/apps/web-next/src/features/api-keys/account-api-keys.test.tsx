// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

const apiKey = {
  id: "key-1",
  key_prefix: "sk_ab",
  key_suffix: "wxyz",
  name: "Min integration",
  key_type: "sk_",
  permission: "read",
  scope_type: "tenant",
  state: "active",
  expires_at: null,
  created_at: "2026-09-01T08:00:00Z"
} as Schema<"ApiKeyV2">;

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      const data =
        path === "/api/v1/api-keys"
          ? { items: [apiKey], next_cursor: null, total_count: 1 }
          : path === "/api/v1/api-keys/notification-preferences"
            ? { enabled: false, days_before_expiry: [7], auto_follow_published_assistants: false }
            : {};
      return Promise.resolve({ data, response: new Response("{}") });
    }
  }
}));

import { ApiKeys } from "./account-api-keys";

afterEach(cleanup);

describe("ApiKeys (account)", () => {
  it("names the key table like the account page it is on", async () => {
    renderInApp(<ApiKeys />, { appContext: testAppContext({ permissions: ["api_keys"] }) });

    const table = await screen.findByRole("table", { name: "API-nycklar" });
    expect(await within(table).findByText("Min integration")).toBeTruthy();
  });

  it("shows the keys in the panel of the selected state tab", async () => {
    const { container } = renderInApp(<ApiKeys />, {
      appContext: testAppContext({ permissions: ["api_keys"] })
    });

    const panel = screen.getByRole("tabpanel", { name: "Aktiv" });
    expect(screen.getByRole("tab", { name: "Aktiv" }).getAttribute("aria-controls")).toBe(panel.id);
    expect(await within(panel).findByText("Min integration")).toBeTruthy();
    await expectNoAxeViolations(container);
  });
});
