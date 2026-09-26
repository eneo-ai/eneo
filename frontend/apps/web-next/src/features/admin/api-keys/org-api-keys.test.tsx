// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { renderInApp, testAppContext } from "@/test/render";

const apiKey = {
  id: "key-1",
  key_prefix: "sk_ab",
  key_suffix: "wxyz",
  name: "Ärendesystemet",
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
        path === "/api/v1/admin/api-keys"
          ? { items: [apiKey], next_cursor: null }
          : path === "/api/v1/admin/api-keys/{id}/usage"
            ? {
                summary: { total_events: 1, used_events: 1, auth_failed_events: 0 },
                items: [
                  {
                    id: "event-1",
                    timestamp: "2026-09-20T08:00:00Z",
                    action: "api_key_used",
                    outcome: "used",
                    method: "GET",
                    request_path: "/api/v1/assistants/",
                    ip_address: "10.0.0.1"
                  }
                ],
                next_cursor: null
              }
            : {};
      return Promise.resolve({ data, response: new Response("{}") });
    }
  }
}));

import { OrgApiKeysPage } from "./org-api-keys";
import { ApiKeyUsageDialog } from "./usage-dialog";

afterEach(cleanup);

describe("OrgApiKeysPage", () => {
  it("names the key table by the page title", async () => {
    renderInApp(<OrgApiKeysPage />, { appContext: testAppContext({ permissions: ["admin"] }) });

    const table = await screen.findByRole("table", { name: "API-nycklar" });
    expect(await within(table).findByText("Ärendesystemet")).toBeTruthy();
  });
});

describe("ApiKeyUsageDialog", () => {
  it("names the usage table", async () => {
    renderInApp(<ApiKeyUsageDialog apiKey={apiKey} open onOpenChange={() => {}} />);

    const dialog = await screen.findByRole("dialog", { name: "Ärendesystemet · Användning" });
    const table = await within(dialog).findByRole("table", { name: "Användning" });
    expect(within(table).getByText("api_key_used")).toBeTruthy();
  });
});
