// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const state = vi.hoisted(() => ({
  items: [] as Schema<"ApiKeyV2">[],
  next: [] as Schema<"ApiKeyV2">[],
  failFirst: false,
  failNext: false,
  requests: [] as { cursor?: string | null; state?: string | null }[]
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string, options?: { params?: { query?: { cursor?: string; state?: string } } }) => {
      let data: unknown = {};
      if (path === "/api/v1/api-keys") {
        const query = options?.params?.query ?? {};
        state.requests.push(query);
        if (query.cursor ? state.failNext : state.failFirst)
          return Promise.reject(new Error("Temporarily unavailable"));
        data = {
          items: query.cursor ? state.next : state.items,
          next_cursor: !query.cursor && state.next.length > 0 ? "page-2" : null
        };
      } else if (path === "/api/v1/spaces/") {
        data = { items: [{ id: "space-1", name: "Upphandling" }] };
      } else if (path === "/api/v1/spaces/type/organization/") {
        data = { id: "space-1", name: "Upphandling" };
      } else if (path === "/api/v1/spaces/{id}/applications/") {
        data = { assistants: { items: [] }, apps: { items: [] } };
      }
      return Promise.resolve({ data, response: new Response("{}") });
    }
  }
}));

import { UserApiKeyList } from "./user-api-key-list";

function key(id: string, overrides: Partial<Schema<"ApiKeyV2">> = {}): Schema<"ApiKeyV2"> {
  return {
    id,
    name: `Integration ${id}`,
    key_prefix: "sk_test",
    key_suffix: id,
    key_type: "sk_",
    permission: "read",
    scope_type: "tenant",
    state: "active",
    ...overrides
  };
}

beforeEach(() => {
  state.items = [key("1"), key("2"), key("3"), key("4")];
  state.next = [];
  state.failFirst = false;
  state.failNext = false;
  state.requests = [];
});
afterEach(cleanup);

describe("UserApiKeyList", () => {
  it("shows scope, service ownership, restrictions, last use and state changes in the row", async () => {
    state.items = [
      key("1", {
        description: "Test integration description",
        scope_type: "space",
        scope_id: "space-1",
        ownership: "service",
        state: "suspended",
        suspended_at: "2026-09-30T10:00:00Z",
        suspended_reason_code: "admin_action",
        suspended_reason_text: "Integration under review",
        last_used_at: "2026-09-29T10:00:00Z",
        allowed_ips: ["192.0.2.0/24"],
        rate_limit: 120
      }),
      key("2", { key_type: "pk_", allowed_origins: ["https://example.test"] })
    ];
    const { container } = renderInApp(<UserApiKeyList limit={25} onRotated={vi.fn()} />);
    const row = await screen.findByRole("row", { name: /Integration 1/ });
    expect(await within(row).findByText("Upphandling")).toBeTruthy();
    for (const text of [
      "Test integration description",
      "Tjänstenyckel",
      "192.0.2.0/24",
      "120/h",
      "Administratörsåtgärd · Integration under review"
    ])
      expect(within(row).getByText(text)).toBeTruthy();
    await waitFor(() => {
      expect(within(row).getByText(/^29 sep\. 2026/)).toBeTruthy();
      expect(within(row).getByText(/^30 sep\. 2026/)).toBeTruthy();
    });
    expect(screen.getByText("https://example.test")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("searches loaded names, descriptions and suffixes, retains pages and refreshes the selected filter", async () => {
    state.items[0] = key("1", { description: "Target system" });
    state.next = [key("5", { name: "Target archive" })];
    renderInApp(<UserApiKeyList limit={25} onRotated={vi.fn()} />);
    const search = await screen.findByRole("textbox", { name: "Sök API-nycklar" });
    fireEvent.change(search, { target: { value: "target" } });
    expect(screen.getByText("Integration 1")).toBeTruthy();
    expect(screen.queryByText("Integration 2")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ladda mer" }));
    expect(await screen.findByText("Target archive")).toBeTruthy();
    expect(screen.getByText("Integration 1")).toBeTruthy();
    fireEvent.change(search, { target: { value: "4" } });
    expect(screen.getByText("Integration 4")).toBeTruthy();
    fireEvent.change(search, { target: { value: "" } });
    fireEvent.click(screen.getByRole("tab", { name: "Alla statusar" }));
    await waitFor(() => expect(state.requests.at(-1)?.state).toBeNull());
    await screen.findByRole("table", { name: "API-nycklar" });
    const beforeRefresh = state.requests.length;
    fireEvent.click(screen.getByRole("button", { name: "Uppdatera" }));
    await waitFor(() => expect(state.requests.length).toBeGreaterThan(beforeRefresh));
    expect(state.requests.at(-1)?.state).toBeNull();
  });

  it("retains loaded keys and a nonmatching search when a later page fails, then retries", async () => {
    state.next = [key("5", { name: "Target archive" })];
    state.failNext = true;
    renderInApp(<UserApiKeyList limit={25} onRotated={vi.fn()} />);
    const search = await screen.findByRole("textbox", { name: "Sök API-nycklar" });
    fireEvent.change(search, { target: { value: "target" } });
    expect(screen.getByText("Inga matchande API-nycklar")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ladda mer" }));
    const retry = await screen.findByRole("button", { name: /Försök igen/ });
    expect((search as HTMLInputElement).value).toBe("target");
    state.failNext = false;
    fireEvent.click(retry);
    expect(await screen.findByText("Target archive")).toBeTruthy();
    fireEvent.change(search, { target: { value: "" } });
    expect(screen.getByText("Integration 1")).toBeTruthy();
  });

  it("reports a failed initial read instead of an empty list, and offers retry", async () => {
    state.failFirst = true;
    renderInApp(<UserApiKeyList limit={25} onRotated={vi.fn()} />);
    const retry = await screen.findByRole("button", { name: /Försök igen/ });
    expect(screen.queryByText("Inga API-nycklar")).toBeNull();
    state.failFirst = false;
    fireEvent.click(retry);
    expect(await screen.findByText("Integration 1")).toBeTruthy();
  });
});
