// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";

const state = vi.hoisted(() => ({
  items: [] as Schema<"ApiKeyV2">[],
  next: [] as Schema<"ApiKeyV2">[],
  failFirst: false,
  failNext: false,
  requests: [] as { cursor?: string | null; state?: string | null }[],
  spaceRequests: [] as { include_applications?: boolean }[],
  patches: [] as { path: string; options: unknown }[]
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (
      path: string,
      options?: {
        params?: { query?: { cursor?: string; state?: string; include_applications?: boolean } };
      }
    ) => {
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
        state.spaceRequests.push(options?.params?.query ?? {});
        data = { items: [{ id: "space-1", name: "Upphandling" }] };
      } else if (path === "/api/v1/spaces/type/organization/") {
        data = { id: "space-1", name: "Upphandling" };
      } else if (path === "/api/v1/spaces/{id}/applications/") {
        data = {
          assistants: { items: [{ id: "assistant-1", name: "Avtalsstöd" }] },
          apps: { items: [] }
        };
      }
      return Promise.resolve({ data, response: new Response("{}") });
    },
    PATCH: (path: string, options: unknown) => {
      state.patches.push({ path, options });
      return Promise.resolve({ data: {}, response: new Response("{}") });
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
  state.spaceRequests = [];
  state.patches = [];
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
    expect(state.spaceRequests).toEqual([{ include_personal: true, include_applications: false }]);
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

  it("gives the column of row menus a header a screen reader can say", async () => {
    state.items = [key("1")];
    renderInApp(<UserApiKeyList limit={25} onRotated={vi.fn()} />);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").at(-1)?.textContent).toBe("Åtgärder");
  });

  it("requests application names when refreshed keys need them, with a distinct spaces response", async () => {
    state.items = [key("1", { scope_type: "space", scope_id: "space-1" })];
    const { queryClient } = renderInApp(<UserApiKeyList limit={25} onRotated={vi.fn()} />);
    await screen.findByText("Upphandling");
    state.items = [key("2", { scope_type: "assistant", scope_id: "assistant-1" })];
    await act(async () => queryClient.invalidateQueries({ queryKey: ["api-keys"] }));
    expect(await screen.findByText("Avtalsstöd")).toBeTruthy();
    expect(state.spaceRequests).toEqual([
      { include_personal: true, include_applications: false },
      { include_personal: true, include_applications: true }
    ]);
  });

  it("searches loaded names, descriptions and suffixes, retains pages and refreshes the selected filter", async () => {
    state.items[0] = key("1", { description: "Target system" });
    state.next = [key("5", { name: "Target archive" })];
    renderInApp(<UserApiKeyList limit={25} onRotated={vi.fn()} />);
    // The field is there from the start (disabled while loading): wait for the keys.
    await screen.findByText("Integration 1");
    const search = screen.getByRole("textbox", { name: "Sök API-nycklar" });
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

  it("keeps the search field in place while the keys load, disabled, so the table does not move", async () => {
    renderInApp(<UserApiKeyList limit={25} onRotated={vi.fn()} />);
    const search = screen.getByRole("textbox", { name: "Sök API-nycklar" });
    expect(search.getAttribute("aria-disabled")).toBe("true");
    // The label and its description say what is searched; a placeholder only repeated them.
    expect(search.getAttribute("placeholder") ?? "").toBe("");

    await screen.findByText("Integration 1");
    expect(
      (screen.getByRole("textbox", { name: "Sök API-nycklar" }) as HTMLInputElement).disabled
    ).toBe(false);
  });

  it("retains loaded keys and a nonmatching search when a later page fails, then retries", async () => {
    state.next = [key("5", { name: "Target archive" })];
    state.failNext = true;
    renderInApp(<UserApiKeyList limit={25} onRotated={vi.fn()} />);
    await screen.findByText("Integration 1");
    const search = screen.getByRole("textbox", { name: "Sök API-nycklar" });
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

  it("keeps an open editor and its typed name when a turn swaps the table and the rows", async () => {
    state.items[1] = key("2", { owner_user_id: "user-1" });
    renderInApp(<UserApiKeyList limit={25} onRotated={vi.fn()} />);
    const more = await screen.findByRole("button", { name: "Fler åtgärder för Integration 2" });
    more.focus();
    fireEvent.keyDown(more, { key: "Enter" });
    const menu = document.getElementById(more.getAttribute("aria-controls") ?? "")!;
    fireEvent.click(await within(menu).findByRole("menuitem", { name: "Redigera" }));
    const dialog = await screen.findByRole("dialog", { name: "Redigera API-nyckel" });
    fireEvent.change(await within(dialog).findByLabelText("Namn"), {
      target: { value: "Ärendeportalen" }
    });

    // A phone turned to portrait, then back: the rows replace the table, and the table the rows.
    act(() => setViewport("phone"));
    expect(await screen.findByRole("list", { name: "API-nycklar" })).toBeTruthy();
    act(() => setViewport("desktop"));
    expect(await screen.findByRole("table", { name: "API-nycklar" })).toBeTruthy();

    const open = screen.getByRole("dialog", { name: "Redigera API-nyckel" });
    expect((within(open).getByLabelText("Namn") as HTMLInputElement).value).toBe("Ärendeportalen");
    fireEvent.click(within(open).getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(state.patches).toEqual([
        {
          path: "/api/v1/api-keys/{id}",
          options: { params: { path: { id: "2" } }, body: { name: "Ärendeportalen" } }
        }
      ])
    );
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

describe("UserApiKeyList on a phone", () => {
  it("lists the keys as rows with their name, key, state, scope, expiry and menu", async () => {
    setViewport("phone");
    state.items = [
      key("1", {
        scope_type: "space",
        scope_id: "space-1",
        ownership: "service",
        state: "suspended",
        suspended_at: "2026-09-30T10:00:00Z",
        suspended_reason_code: "admin_action",
        suspended_reason_text: "Integration under review"
      }),
      key("2")
    ];
    renderInApp(<UserApiKeyList limit={25} onRotated={vi.fn()} />);
    const list = await screen.findByRole("list", { name: "API-nycklar" });
    expect(screen.queryByRole("table")).toBeNull();
    const [first, second] = within(list).getAllByRole("listitem");
    expect(await within(first!).findByText("Yta · Upphandling · Läs")).toBeTruthy();
    for (const text of [
      "Integration 1",
      "sk_test…1",
      "Tjänstenyckel",
      "Pausad",
      "Administratörsåtgärd · Integration under review",
      "Går ut: Aldrig",
      "Senast använd: Aldrig"
    ])
      expect(within(first!).getByText(text)).toBeTruthy();
    expect(
      within(first!).getByRole("button", { name: "Fler åtgärder för Integration 1" })
    ).toBeTruthy();
    expect(within(second!).getByText("Organisation · Läs")).toBeTruthy();

    // A search narrows the rows as it does the table.
    fireEvent.change(screen.getByRole("textbox", { name: "Sök API-nycklar" }), {
      target: { value: "2" }
    });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    await expectNoAxeViolations(document.body);

    act(() => setViewport("desktop"));
    expect(screen.getByRole("table", { name: "API-nycklar" })).toBeTruthy();
  });
});
