// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

import { OrgApiKeysPage } from "./org-api-keys";

const apiKey = {
  id: "key-1",
  key_prefix: "sk_ab",
  key_suffix: "wxyz",
  name: "Ärendesystemet",
  key_type: "sk_",
  permission: "read",
  scope_type: "space",
  scope_id: "space-1",
  ownership: "user",
  owner_user_id: "user-2",
  owner_user: { id: "user-2", email: "kim@example.se", username: null },
  rate_limit: 600,
  last_used_at: null,
  state: "active",
  expires_at: null,
  created_at: "2026-09-01T08:00:00Z"
} as Schema<"ApiKeyV2">;

const secret = `sk_${"a1b2c3d4".repeat(5)}`;
const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
const notFound = () =>
  Promise.resolve({
    error: { message: "Not found" },
    response: new Response("{}", { status: 404 })
  });

function serve() {
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/admin/api-keys") {
      return ok({ items: [apiKey], next_cursor: null, total_count: 7 });
    }
    if (path === "/api/v1/admin/api-keys/{id}") return ok({ ...apiKey, name: "Hittad nyckel" });
    if (path === "/api/v1/spaces/") {
      return ok({ items: [{ id: "space-1", name: "Upphandling", applications: null }] });
    }
    if (path === "/api/v1/audit/config/actions") {
      return ok({
        actions: [
          { action: "api_key_used", enabled: false, category: "security_events" },
          { action: "api_key_auth_failed", enabled: true, category: "security_events" }
        ]
      });
    }
    return notFound();
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const listQueries = () =>
  api.GET.mock.calls
    .filter(([path]) => path === "/api/v1/admin/api-keys")
    .map(([, options]) => (options as { params: { query: Record<string, unknown> } }).params.query);

function show() {
  serve();
  return renderInApp(<OrgApiKeysPage />, {
    appContext: testAppContext({
      permissions: ["admin"],
      settings: { api_key_expiry_notifications: true }
    })
  });
}

describe("OrgApiKeysPage", () => {
  it("lists keys with their owner, scope, rate limit and last use", async () => {
    const { container } = show();
    const table = await screen.findByRole("table", { name: "API-nycklar" });
    expect(await within(table).findByText("Ärendesystemet")).toBeTruthy();
    expect(within(table).getByRole("link", { name: "kim@example.se" }).getAttribute("href")).toBe(
      "/admin/users?search=kim%40example.se"
    );
    expect(await within(table).findByText("Upphandling")).toBeTruthy();
    expect(within(table).getByText("600/h")).toBeTruthy();
    // Never used, and no expiry.
    expect(within(table).getAllByText("Aldrig")).toHaveLength(2);
    expect(
      within(table).getByRole("button", { name: "Fler åtgärder för Ärendesystemet" })
    ).toBeTruthy();
    expect(screen.getByText("Visar 1 av 7 nycklar totalt")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("shows the keys in the panel of the selected state tab, every state included", async () => {
    show();
    const panel = screen.getByRole("tabpanel", { name: "Aktiv" });
    expect(screen.getByRole("tab", { name: "Aktiv" }).getAttribute("aria-controls")).toBe(panel.id);
    expect(await within(panel).findByText("Ärendesystemet")).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Alla statusar" }));
    await waitFor(() => expect(listQueries().at(-1)?.state).toBeUndefined());
  });

  it("applies the filters together: search, expiry window and page size", async () => {
    show();
    await screen.findByText("Ärendesystemet");
    fireEvent.change(screen.getByLabelText("Sök"), { target: { value: "Diariet" } });
    fireEvent.change(screen.getByLabelText("Utgår inom (dagar)"), { target: { value: "14" } });
    expect(listQueries().every((query) => query.search === undefined)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Tillämpa filter" }));

    await waitFor(() =>
      expect(listQueries().at(-1)).toMatchObject({
        search: "Diariet",
        expires_within_days: 14,
        state: "active"
      })
    );
    expect(screen.getByText("3 filter aktiva")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Rensa alla" }));
    expect(((await screen.findByLabelText("Sök")) as HTMLInputElement).value).toBe("");
    // Only the state tab (Aktiv) narrows the list again.
    expect(screen.getByText("1 filter aktivt")).toBeTruthy();
  });

  it("finds a pasted whole key by lookup, without the key in a list request", async () => {
    show();
    await screen.findByText("Ärendesystemet");
    api.POST.mockReturnValue(ok({ api_key: { id: "key-9" }, match_reason: "exact_secret" }));
    fireEvent.change(screen.getByLabelText("Sök"), { target: { value: secret } });
    expect(screen.getByLabelText("Sök").getAttribute("autocomplete")).toBe("off");
    fireEvent.click(screen.getByRole("button", { name: "Tillämpa filter" }));

    expect(await screen.findByText("Hittad nyckel")).toBeTruthy();
    expect(screen.getByText("Exakt nyckelmatchning")).toBeTruthy();
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/api-keys/lookup", {
      body: { secret }
    });
    expect(JSON.stringify(api.GET.mock.calls)).not.toContain(secret);
  });

  it("searches a whole key that matched nothing by its suffix", async () => {
    show();
    await screen.findByText("Ärendesystemet");
    api.POST.mockReturnValue(notFound());
    fireEvent.change(screen.getByLabelText("Sök"), { target: { value: secret } });
    fireEvent.click(screen.getByRole("button", { name: "Tillämpa filter" }));

    await waitFor(() => expect(listQueries().at(-1)?.search).toBe("a1b2c3d4"));
    expect(JSON.stringify(api.GET.mock.calls)).not.toContain(secret);
  });

  it("saves the expiry-notification switch on toggle and reverts on error", async () => {
    show();
    api.PATCH.mockReturnValue(
      Promise.resolve({ error: { message: "Nope" }, response: new Response("{}", { status: 500 }) })
    );
    const toggle = await screen.findByRole("switch", {
      name: /Aktivera notiser för API-nyckelutgång/
    });
    expect((toggle as HTMLInputElement).checked).toBe(true);
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/settings/api-key-expiry-notifications", {
        body: { enabled: false }
      })
    );
    await waitFor(() => expect((toggle as HTMLInputElement).checked).toBe(true));
  });

  it("switches the audit log's tracking of key use", async () => {
    show();
    api.PATCH.mockReturnValue(ok({}));
    const used = await screen.findByRole("switch", { name: /Spåra API-nyckelanvändning/ });
    expect(used.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(used);

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/audit/config/actions", {
        body: { updates: [{ action: "api_key_used", enabled: true }] }
      })
    );
  });

  it("reports a failed lookup with a retry that looks the key up again", async () => {
    show();
    await screen.findByText("Ärendesystemet");
    api.POST.mockReturnValue(
      Promise.resolve({
        error: { message: "Lookup down" },
        response: new Response("{}", { status: 503 })
      })
    );
    fireEvent.change(screen.getByLabelText("Sök"), { target: { value: secret } });
    fireEvent.click(screen.getByRole("button", { name: "Tillämpa filter" }));

    expect(await screen.findByText("Lookup down")).toBeTruthy();
    // A retry that fails again keeps the error and its focused Retry button.
    let fail: (value: unknown) => void = () => {};
    api.POST.mockReturnValue(new Promise((done) => (fail = done)));
    const retry = screen.getByRole("button", { name: /^Försök igen/ });
    retry.focus();
    fireEvent.click(retry);
    expect(screen.getByText("Lookup down")).toBeTruthy();
    fail({ error: { message: "Still down" }, response: new Response("{}", { status: 503 }) });
    expect(await screen.findByText("Still down")).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Försök igen/ }));

    api.POST.mockReturnValue(ok({ api_key: { id: "key-9" } }));
    fireEvent.click(screen.getByRole("button", { name: /^Försök igen/ }));
    expect(await screen.findByText("Hittad nyckel")).toBeTruthy();
    expect(api.POST).toHaveBeenCalledTimes(3);
    // The answer replaced the button: focus is on the list's panel, not lost.
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tabpanel")));
    expect(JSON.stringify(api.GET.mock.calls)).not.toContain('"id":""');
  });

  it("says the list could not be read instead of showing no keys", async () => {
    serve();
    api.GET.mockImplementation((path: string) =>
      path === "/api/v1/admin/api-keys"
        ? Promise.resolve({
            error: { message: "List down" },
            response: new Response("{}", { status: 500 })
          })
        : notFound()
    );
    renderInApp(<OrgApiKeysPage />, { appContext: testAppContext({ permissions: ["admin"] }) });
    expect(await screen.findByText("List down")).toBeTruthy();
    expect(screen.queryByText("Inga API-nycklar hittades")).toBeNull();
  });

  it("filters by a resource given by id, one the admin is not a member of", async () => {
    show();
    await screen.findByText("Ärendesystemet");
    fireEvent.click(screen.getByRole("combobox", { name: "Omfångstyp" }));
    fireEvent.click(await screen.findByRole("option", { name: "Assistent" }));
    fireEvent.change(screen.getByLabelText("Eller ange assistent-ID manuellt"), {
      target: { value: "assistant-77" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Tillämpa filter" }));

    await waitFor(() =>
      expect(listQueries().at(-1)).toMatchObject({
        scope_type: "assistant",
        scope_id: "assistant-77"
      })
    );
  });

  it("shows an unlimited rate limit (-1) as unlimited", async () => {
    serve();
    const listed = api.GET.getMockImplementation()!;
    api.GET.mockImplementation((path: string, options: unknown) =>
      path === "/api/v1/admin/api-keys"
        ? ok({ items: [{ ...apiKey, rate_limit: -1 }], next_cursor: null, total_count: 1 })
        : listed(path, options)
    );
    renderInApp(<OrgApiKeysPage />, { appContext: testAppContext({ permissions: ["admin"] }) });
    const table = await screen.findByRole("table", { name: "API-nycklar" });
    expect(await within(table).findByText("Obegränsad")).toBeTruthy();
  });
});
