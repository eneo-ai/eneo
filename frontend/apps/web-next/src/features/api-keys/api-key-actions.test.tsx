// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";

const api = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  PATCH: vi.fn(),
  PUT: vi.fn(),
  DELETE: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { ApiKeyActions } from "./api-key-actions";
import { EditApiKeyDialog } from "./api-key-form";
import type { ApiKeyMode } from "./api-keys";

type ApiKey = Schema<"ApiKeyV2">;

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
const refused = (message: string) =>
  Promise.resolve({ error: { message }, response: new Response("{}", { status: 400 }) });

const activeKey = {
  id: "key-1",
  key_prefix: "pk_ab",
  key_suffix: "wxyz",
  name: "Webbwidget",
  key_type: "pk_",
  permission: "read",
  scope_type: "tenant",
  ownership: "user",
  owner_user_id: "user-1",
  allowed_origins: ["https://sundsvall.se"],
  resource_permissions: {
    assistants: "read",
    apps: "read",
    spaces: "none",
    knowledge: "none",
    conversations: "none",
    files: "none",
    jobs: "none",
    prompts: "none"
  },
  rate_limit: 100,
  state: "active",
  expires_at: "2026-12-01T22:59:59Z",
  created_at: "2026-09-01T08:00:00Z"
} as ApiKey;

let subscriptions: { target_type: string; target_id: string }[] = [];

function serve({ constraints = {} }: { constraints?: object } = {}) {
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/api-keys/policy-constraints") return ok(constraints);
    if (path === "/api/v1/api-keys/notification-subscriptions") return ok({ items: subscriptions });
    if (path === "/api/v1/api-keys/{id}/usage" || path === "/api/v1/admin/api-keys/{id}/usage") {
      return ok({
        summary: {
          total_events: 3,
          used_events: 2,
          auth_failed_events: 1,
          last_seen_at: "2026-10-27T08:00:00Z"
        },
        items: [],
        limit: 50,
        next_cursor: null
      });
    }
    return ok({});
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  subscriptions = [];
});

function show(apiKey: ApiKey = activeKey, { mode = "user" }: { mode?: ApiKeyMode } = {}) {
  const onRotated = vi.fn();
  const queryClient = testQueryClient();
  renderInApp(<ApiKeyActions apiKey={apiKey} mode={mode} onRotated={onRotated} />, {
    queryClient,
    appContext: testAppContext({ permissions: ["api_keys"] })
  });
  return { onRotated, queryClient };
}

async function openMenu(name = activeKey.name) {
  const trigger = screen.getByRole("button", { name: `Fler åtgärder för ${name}` });
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "Enter" });
  return screen.findByRole("menu");
}

async function choose(item: string, name?: string) {
  const menu = await openMenu(name);
  fireEvent.click(within(menu).getByRole("menuitem", { name: item }));
}

const items = async (name?: string) =>
  within(await openMenu(name))
    .getAllByRole("menuitem")
    .map((item) => item.textContent?.trim());

describe("ApiKeyActions", () => {
  it("offers what an active, a revoked and an expired key allow", async () => {
    serve();
    show();
    expect(await items()).toEqual([
      "Visa detaljer",
      "Användning",
      "Redigera",
      "Rotera",
      "Ändra utgångsdatum",
      "Följ utgångspåminnelser",
      "Pausa",
      "Återkalla"
    ]);
    cleanup();

    show({ ...activeKey, state: "revoked" });
    expect(await items()).toEqual(["Visa detaljer", "Användning", "Redigera", "Ta bort permanent"]);
    cleanup();

    show({ ...activeKey, state: "expired" });
    expect(await items()).toEqual([
      "Visa detaljer",
      "Användning",
      "Redigera",
      "Återkalla",
      "Ta bort permanent"
    ]);
  });

  it("suspends only after a dialog that names the key and takes a reason", async () => {
    serve();
    api.POST.mockReturnValue(ok(activeKey));
    show();
    await choose("Pausa");
    expect(api.POST).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("alertdialog", { name: "Pausa API-nyckel" });
    expect(within(dialog).getByText("Webbwidget")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Anledning (valfritt)"), {
      target: { value: "Misstänkt läcka" }
    });
    await expectNoAxeViolations(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Pausa" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/api-keys/{id}/suspend", {
        params: { path: { id: "key-1" } },
        body: { reason_code: "user_request", reason_text: "Misstänkt läcka" }
      })
    );
  });

  it("revokes as an admin through the admin endpoint, with the admin's reason code", async () => {
    serve();
    api.POST.mockReturnValue(ok(activeKey));
    show(activeKey, { mode: "admin" });
    await choose("Återkalla");
    const dialog = await screen.findByRole("alertdialog", { name: "Återkalla API-nyckel" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Återkalla" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/api-keys/{id}/revoke", {
        params: { path: { id: "key-1" } },
        body: { reason_code: "admin_action", reason_text: null }
      })
    );
  });

  it("deletes a revoked key for good after a dialog that names it", async () => {
    serve();
    api.POST.mockReturnValue(Promise.resolve({ response: new Response(null, { status: 204 }) }));
    show({ ...activeKey, state: "revoked" });
    await choose("Ta bort permanent");
    const dialog = await screen.findByRole("alertdialog", {
      name: "Ta bort API-nyckel permanent?"
    });
    expect(within(dialog).getByText("Webbwidget")).toBeTruthy();
    expect(within(dialog).getByText("pk_ab…wxyz")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort permanent" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/api-keys/{id}/purge", {
        params: { path: { id: "key-1" } }
      })
    );
  });

  it("edits only what changed, and keeps the dialog open on a refusal", async () => {
    serve();
    api.PATCH.mockReturnValue(refused("Rate limit exceeds tenant maximum."));
    show();
    await choose("Redigera");
    const dialog = await screen.findByRole("dialog", { name: "Redigera API-nyckel" });
    // A public key's origins stay editable.
    expect(await within(dialog).findByText("https://sundsvall.se")).toBeTruthy();
    const rate = within(dialog).getByLabelText(/Anropsgräns/);
    fireEvent.change(rate, { target: { value: "250" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/api-keys/{id}", {
        params: { path: { id: "key-1" } },
        body: { rate_limit: 250 }
      })
    );
    expect(await within(dialog).findByText("Rate limit exceeds tenant maximum.")).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "Redigera API-nyckel" })).toBeTruthy();

    // Cancelled and opened again, the form starts over: no earlier refusal.
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await choose("Redigera");
    const again = await screen.findByRole("dialog", { name: "Redigera API-nyckel" });
    await within(again).findByLabelText(/Anropsgräns/);
    expect(within(again).queryByText("Rate limit exceeds tenant maximum.")).toBeNull();
  });

  it("renames a key whose rate limit a later, lower policy maximum would refuse", async () => {
    serve({ constraints: { max_rate_limit: 500 } });
    api.PATCH.mockReturnValue(ok(activeKey));
    show({ ...activeKey, rate_limit: 800 });
    await choose("Redigera");
    const dialog = await screen.findByRole("dialog", { name: "Redigera API-nyckel" });
    fireEvent.change(await within(dialog).findByLabelText("Beskrivning"), {
      target: { value: "För webbplatsen" }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/api-keys/{id}", {
        params: { path: { id: "key-1" } },
        body: { description: "För webbplatsen" }
      })
    );
  });

  it("edits only the name and description of a revoked key", async () => {
    serve();
    api.PATCH.mockReturnValue(ok(activeKey));
    // A legacy key without stored access: a full edit would send it.
    show({ ...activeKey, state: "revoked", resource_permissions: null });
    await choose("Redigera");
    const dialog = await screen.findByRole("dialog", { name: "Redigera API-nyckel" });
    expect(
      await within(dialog).findByText(
        "Skyddsregler kan bara ändras för aktiva eller pausade nycklar."
      )
    ).toBeTruthy();
    expect(within(dialog).queryByLabelText(/Anropsgräns/)).toBeNull();

    fireEvent.change(within(dialog).getByLabelText("Namn"), {
      target: { value: "Gamla widgeten" }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/api-keys/{id}", {
        params: { path: { id: "key-1" } },
        body: { name: "Gamla widgeten" }
      })
    );
  });

  it("sends only this edit for a legacy key restricted elsewhere while the dialog was open", async () => {
    serve();
    api.PATCH.mockReturnValue(ok(activeKey));
    const legacy = {
      ...activeKey,
      key_type: "sk_",
      permission: "write",
      allowed_origins: null,
      allowed_ips: null,
      resource_permissions: null
    } as ApiKey;
    const { rerender } = renderInApp(
      <EditApiKeyDialog apiKey={legacy} mode="admin" open onOpenChange={() => {}} />,
      { appContext: testAppContext({ permissions: ["admin"] }) }
    );
    const dialog = await screen.findByRole("dialog", { name: "Redigera API-nyckel" });
    const description = await within(dialog).findByLabelText("Beskrivning");
    rerender(
      <EditApiKeyDialog
        apiKey={{ ...legacy, permission: "read", resource_permissions: { spaces: "read" } }}
        mode="admin"
        open
        onOpenChange={() => {}}
      />
    );
    fireEvent.change(description, { target: { value: "Roterad av drift" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/admin/api-keys/{id}", {
        params: { path: { id: "key-1" } },
        body: { description: "Roterad av drift" }
      })
    );
  });

  it("sends only this edit when the key changed elsewhere while the dialog was open", async () => {
    serve();
    api.PATCH.mockReturnValue(ok(activeKey));
    const secretKey = {
      ...activeKey,
      key_type: "sk_",
      allowed_origins: null,
      allowed_ips: null,
      resource_permissions: { ...activeKey.resource_permissions, spaces: "write" }
    } as ApiKey;
    const { rerender } = renderInApp(
      <EditApiKeyDialog apiKey={secretKey} mode="admin" open onOpenChange={() => {}} />,
      { appContext: testAppContext({ permissions: ["admin"] }) }
    );
    const dialog = await screen.findByRole("dialog", { name: "Redigera API-nyckel" });
    const description = await within(dialog).findByLabelText("Beskrivning");
    // Another admin restricts the key; the list refetches it under the open dialog.
    rerender(
      <EditApiKeyDialog
        apiKey={{
          ...secretKey,
          allowed_ips: ["10.0.0.0/8"],
          resource_permissions: { ...secretKey.resource_permissions, spaces: "read" }
        }}
        mode="admin"
        open
        onOpenChange={() => {}}
      />
    );
    fireEvent.change(description, { target: { value: "Roterad av drift" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/admin/api-keys/{id}", {
        params: { path: { id: "key-1" } },
        body: { description: "Roterad av drift" }
      })
    );
  });

  it("changes the expiry with the current and the new date, and shows a refusal in place", async () => {
    serve({ constraints: { require_expiration: true, max_expiration_days: 365 } });
    api.POST.mockReturnValue(refused("Expiration exceeds tenant maximum."));
    show(activeKey, { mode: "admin" });
    await choose("Ändra utgångsdatum");
    const dialog = await screen.findByRole("dialog", { name: "Ändra API-nyckelns utgång" });
    const expiry = await within(dialog).findByRole("radiogroup", { name: "Utgångsdatum" });
    // The policy requires an expiry: "no expiry" is not offered.
    expect(within(expiry).queryByRole("radio", { name: "Inget utgångsdatum" })).toBeNull();
    expect(within(dialog).getByText("Nuvarande utgång")).toBeTruthy();

    fireEvent.click(within(expiry).getByRole("radio", { name: "90 dagar" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara utgång" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/api-keys/{id}/extend", {
        params: { path: { id: "key-1" } },
        body: { expires_at: expect.any(String) }
      })
    );
    expect(await within(dialog).findByText("Expiration exceeds tenant maximum.")).toBeTruthy();
  });

  it("rotates with the policy's grace period or none, and hands over the secret once", async () => {
    serve({ constraints: { rotation_grace_hours: 48 } });
    api.POST.mockReturnValue(
      ok({ api_key: { ...activeKey, id: "key-2" }, secret: "pk_rotated_secret" })
    );
    const { onRotated, queryClient } = show();
    await choose("Rotera");
    const dialog = await screen.findByRole("dialog", { name: "Rotera API-nyckel" });
    expect(await within(dialog).findByText("48 timmar")).toBeTruthy();
    fireEvent.click(within(dialog).getByLabelText("Revokera nuvarande nyckel direkt"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Rotera" }));

    await waitFor(() => expect(onRotated).toHaveBeenCalledWith("pk_rotated_secret"));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/api-keys/{id}/rotate", {
      params: { path: { id: "key-1" } },
      body: { disable_grace_period: true }
    });
    const cached = JSON.stringify(
      queryClient
        .getMutationCache()
        .getAll()
        .map((mutation) => mutation.state)
    );
    expect(cached).not.toContain("pk_rotated_secret");
  });

  it("follows one key's reminders, and says when its scope's cover it", async () => {
    serve();
    api.PUT.mockImplementation(() => {
      subscriptions = [{ target_type: "key", target_id: "key-1" }];
      return ok({ items: subscriptions });
    });
    show();
    await choose("Följ utgångspåminnelser");
    await waitFor(() =>
      expect(api.PUT).toHaveBeenCalledWith(
        "/api/v1/api-keys/notification-subscriptions/{target_type}/{target_id}",
        { params: { path: { target_type: "key", target_id: "key-1" } } }
      )
    );
    expect(await items()).toContain("Avfölj utgångspåminnelser");
    cleanup();

    // A key whose assistant is followed is covered by it, wherever it is listed.
    subscriptions = [{ target_type: "assistant", target_id: "assistant-1" }];
    show({ ...activeKey, scope_type: "assistant", scope_id: "assistant-1" });
    const menu = await openMenu();
    expect(
      (await within(menu).findByRole("menuitem", { name: "Följs via scope" })).getAttribute(
        "aria-disabled"
      )
    ).toBe("true");
  });

  it("shows another user's personal key but does not manage it", async () => {
    serve();
    show({ ...activeKey, owner_user_id: "user-2" });
    const menu = await openMenu();
    for (const name of ["Redigera", "Rotera", "Pausa", "Återkalla"]) {
      expect(within(menu).getByRole("menuitem", { name }).getAttribute("aria-disabled")).toBe(
        "true"
      );
    }
    expect(
      within(menu).getByRole("menuitem", { name: "Visa detaljer" }).getAttribute("aria-disabled")
    ).toBeNull();
  });

  it("shows a key's restrictions and its usage with when it was last seen", async () => {
    serve();
    show();
    await choose("Visa detaljer");
    const dialog = await screen.findByRole("dialog", { name: "Webbwidget" });
    expect(within(dialog).getByText("https://sundsvall.se")).toBeTruthy();
    expect(within(dialog).getByText("100/h")).toBeTruthy();

    fireEvent.mouseDown(within(dialog).getByRole("tab", { name: "Användning" }));
    expect(await within(dialog).findByText("Misslyckade anrop")).toBeTruthy();
    expect(api.GET).toHaveBeenCalledWith("/api/v1/api-keys/{id}/usage", expect.anything());
    // The audit log is an admin's.
    expect(within(dialog).queryByText("Öppna i granskningsloggar")).toBeNull();
    await expectNoAxeViolations(dialog);
  });

  it("does not rotate or change the expiry while the policy cannot be read", async () => {
    serve();
    api.GET.mockImplementation((path: string) =>
      path === "/api/v1/api-keys/policy-constraints"
        ? Promise.resolve({
            error: { message: "Policy unavailable" },
            response: new Response("{}", { status: 503 })
          })
        : ok({ items: [] })
    );
    show();
    await choose("Rotera");
    const rotate = await screen.findByRole("dialog", { name: "Rotera API-nyckel" });
    expect(await within(rotate).findByText("Policy unavailable")).toBeTruthy();
    expect(within(rotate).queryByText(/24 timmar/)).toBeNull();
    fireEvent.click(within(rotate).getByRole("button", { name: "Rotera" }));
    expect(api.POST).not.toHaveBeenCalled();
    fireEvent.keyDown(rotate, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await choose("Ändra utgångsdatum");
    const extend = await screen.findByRole("dialog", { name: "Ändra API-nyckelns utgång" });
    expect(await within(extend).findByText("Policy unavailable")).toBeTruthy();
    expect(within(extend).queryByRole("radiogroup")).toBeNull();
  });
});
