// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

const signIn = vi.hoisted(() => ({ follow: vi.fn() }));
vi.mock("./service-account-sign-in", async (original) => ({
  ...(await original<typeof import("./service-account-sign-in")>()),
  followServiceAccountSignIn: signIn.follow
}));

import { SharePointAppConfigDialog } from "./sharepoint-app-config-dialog";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const configured: Schema<"TenantSharePointAppPublic"> = {
  id: "app-1",
  tenant_id: "tenant-1",
  client_id: "c0ffee",
  client_secret_masked: "****a1b2",
  tenant_domain: "sundsvall.onmicrosoft.com",
  is_active: true,
  auth_method: "service_account",
  auth_status: "ok",
  service_account_email: "service@example.se",
  certificate_path: null,
  created_by: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z"
};

async function renderDialog(config: typeof configured | null, queryClient = testQueryClient()) {
  api.GET.mockImplementation(() => ok(config));
  renderInApp(
    <SharePointAppConfigDialog open onOpenChange={() => {}} onRequestDelete={() => {}} />,
    { queryClient }
  );
  const dialog = screen.getByRole("dialog", { name: "Konfigurera SharePoint-app" });
  // Loaded: the current configuration, or the fields for a first one.
  if (config) await within(dialog).findByRole("button", { name: "Uppdatera secret" });
  else await within(dialog).findByLabelText(/^Klient-ID/);
  return dialog;
}

const field = (dialog: HTMLElement, name: RegExp) =>
  within(dialog).getByLabelText(name) as HTMLInputElement;

afterEach(() => vi.clearAllMocks());

describe("SharePointAppConfigDialog", () => {
  it("tests stored credentials without sending a masked secret and explains Microsoft failures", async () => {
    api.POST.mockImplementation(() =>
      ok({ success: false, error_message: "invalid_client: AADSTS7000215" })
    );
    const dialog = await renderDialog(configured);
    fireEvent.click(within(dialog).getByRole("button", { name: "Testa anslutningen" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledExactlyOnceWith("/api/v1/admin/sharepoint/app/test")
    );
    expect(
      await within(dialog).findByText(/Klienthemligheten är fel eller har gått ut/)
    ).toBeTruthy();
    expect(JSON.stringify(api.POST.mock.calls)).not.toContain(configured.client_secret_masked);
    expect(within(dialog).getByText("Autentiseringsmetod")).toBeTruthy();
    expect(within(dialog).getByText("Inloggning verifierad")).toBeTruthy();
  });

  it.each(["ok", "error"] as const)(
    "offers service-account reauthentication with %s credentials",
    async (auth_status) => {
      const start = { auth_url: "https://login.microsoftonline.com/start", state: "fresh-state" };
      api.POST.mockImplementation(() => ok(start));
      const dialog = await renderDialog({ ...configured, auth_status });
      fireEvent.click(within(dialog).getByRole("button", { name: "Logga in igen med Microsoft" }));
      await waitFor(() =>
        expect(api.POST).toHaveBeenCalledWith(
          "/api/v1/admin/sharepoint/service-account/auth/reauth",
          expect.objectContaining({
            body: { redirect_uri: `${window.location.origin}/integrations/callback/token/` }
          })
        )
      );
      expect(signIn.follow).toHaveBeenCalledWith(start, expect.any(Function));
    }
  );

  it("shows a failed config read with retry instead of an empty credentials form", async () => {
    api.GET.mockImplementation(() =>
      Promise.resolve({
        error: { message: "Unavailable" },
        response: new Response("{}", { status: 503 })
      })
    );
    renderInApp(
      <SharePointAppConfigDialog open onOpenChange={() => {}} onRequestDelete={() => {}} />
    );
    const dialog = screen.getByRole("dialog");
    const retry = await within(dialog).findByRole("button", { name: /Försök igen/ });
    expect(within(dialog).queryByLabelText(/^Klient-ID/)).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Logga in med Microsoft" })).toBeNull();
    api.GET.mockImplementation(() => ok(null));
    fireEvent.click(retry);
    expect(await within(dialog).findByLabelText(/^Klient-ID/)).toBeTruthy();
  });

  it("clears a stale passing stored test and shows guidance after a request failure", async () => {
    api.POST.mockImplementationOnce(() => ok({ success: true })).mockResolvedValueOnce({
      error: { message: "invalid_grant: stale refresh token" },
      response: new Response("{}", { status: 400 })
    });
    const dialog = await renderDialog(configured);
    const test = within(dialog).getByRole("button", { name: "Testa anslutningen" });
    fireEvent.click(test);
    expect(
      await within(dialog).findByText("Anslutningen fungerar", { selector: "p" })
    ).toBeTruthy();
    await waitFor(() => expect(test.getAttribute("aria-busy")).toBeNull());
    fireEvent.click(test);
    expect(within(dialog).queryByText("Anslutningen fungerar", { selector: "p" })).toBeNull();
    expect(
      await within(dialog).findByText(/Den sparade inloggningen gäller inte längre/, {
        selector: "p"
      })
    ).toBeTruthy();
    expect(api.POST).toHaveBeenCalledTimes(2);
  });

  it("retains an unsaved credential draft when a background config read fails", async () => {
    const client = testQueryClient();
    const dialog = await renderDialog(null, client);
    fireEvent.change(field(dialog, /^Klient-ID/), { target: { value: "draft-client" } });
    fireEvent.change(field(dialog, /^Klienthemlighet/), { target: { value: "draft-secret" } });
    api.GET.mockImplementation(() =>
      Promise.resolve({
        error: { message: "Unavailable" },
        response: new Response("{}", { status: 503 })
      })
    );
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["admin-sharepoint-app"] });
    });
    expect(await within(dialog).findByRole("button", { name: /Försök igen/ })).toBeTruthy();
    expect(field(dialog, /^Klient-ID/).value).toBe("draft-client");
    expect(field(dialog, /^Klienthemlighet/).value).toBe("draft-secret");
  });

  it.each(["success", "error"] as const)(
    "keeps a submitted secret out of caches while pending and after %s",
    async (outcome) => {
      const queryClient = testQueryClient();
      const secret = "synthetic-sharepoint-client-secret";
      let finish!: (result: unknown) => void;
      api.POST.mockImplementation(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          })
      );
      const dialog = await renderDialog(configured, queryClient);
      fireEvent.click(within(dialog).getByRole("button", { name: "Uppdatera secret" }));
      fireEvent.change(field(dialog, /^Ny Client Secret/), { target: { value: secret } });
      fireEvent.change(field(dialog, /^Bekräfta klienthemlighet/), { target: { value: secret } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));
      await waitFor(() =>
        expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/sharepoint/app", {
          body: {
            client_id: configured.client_id,
            client_secret: secret,
            tenant_domain: configured.tenant_domain
          }
        })
      );
      const cacheState = () =>
        JSON.stringify({
          mutations: queryClient
            .getMutationCache()
            .getAll()
            .map((mutation) => mutation.state),
          queries: queryClient
            .getQueryCache()
            .getAll()
            .map((query) => query.state)
        });
      expect(cacheState()).not.toContain(secret);
      await act(async () =>
        finish(
          outcome === "success"
            ? { data: null, response: new Response("{}") }
            : { error: { message: "Refused" }, response: new Response("{}", { status: 403 }) }
        )
      );
      await waitFor(() =>
        expect(queryClient.getMutationCache().getAll()[0]?.state.status).toBe(outcome)
      );
      expect(cacheState()).not.toContain(secret);
    }
  );

  it("shows each missing field's problem at the field, and focus moves to the first", async () => {
    const dialog = await renderDialog(null);
    const signIn = within(dialog).getByRole("button", { name: "Logga in med Microsoft" });
    // Never disabled: a disabled button says nothing about what is missing.
    expect((signIn as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(signIn);

    for (const name of [/^Klient-ID/, /^Klienthemlighet/, /^Tenant-ID eller domän/]) {
      expect(field(dialog, name).getAttribute("aria-invalid")).toBe("true");
    }
    expect(within(dialog).getAllByText("Detta fält är obligatoriskt")).toHaveLength(3);
    expect(document.activeElement).toBe(field(dialog, /^Klient-ID/));
    // At the fields instead of a toast, and nothing is sent.
    expect(toast.warning).not.toHaveBeenCalled();
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);

    fireEvent.change(field(dialog, /^Klient-ID/), { target: { value: "c0ffee" } });
    fireEvent.change(field(dialog, /^Klienthemlighet/), { target: { value: "hemlis-1" } });
    fireEvent.change(field(dialog, /^Bekräfta klienthemlighet/), {
      target: { value: "hemlis-1" }
    });
    fireEvent.click(signIn);
    expect(document.activeElement).toBe(field(dialog, /^Tenant-ID eller domän/));
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("shows a mismatched client secret at its confirmation, which takes focus", async () => {
    const dialog = await renderDialog(null);
    fireEvent.change(field(dialog, /^Klient-ID/), { target: { value: "c0ffee" } });
    fireEvent.change(field(dialog, /^Klienthemlighet/), { target: { value: "hemlis-1" } });
    fireEvent.change(field(dialog, /^Bekräfta klienthemlighet/), {
      target: { value: "hemlis-2" }
    });
    fireEvent.change(field(dialog, /^Tenant-ID eller domän/), {
      target: { value: "sundsvall.onmicrosoft.com" }
    });
    for (const input of [field(dialog, /^Klienthemlighet/), field(dialog, /^Bekräfta/)]) {
      expect(input.getAttribute("type")).toBe("password");
      expect(input.getAttribute("autocomplete")).toBe("off");
    }

    fireEvent.click(within(dialog).getByRole("button", { name: "Logga in med Microsoft" }));

    const confirmation = field(dialog, /^Bekräfta klienthemlighet/);
    expect(document.activeElement).toBe(confirmation);
    const error = within(dialog).getByText("Värdena matchar inte");
    expect(confirmation.getAttribute("aria-invalid")).toBe("true");
    expect(confirmation.getAttribute("aria-describedby")).toContain(error.id);
    // At the field instead of a toast, and nothing is sent.
    expect(toast.warning).not.toHaveBeenCalled();
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);
  });

  it("moves focus into a new secret's fields, saves it, and returns focus when dropped", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    const dialog = await renderDialog(configured);
    const update = within(dialog).getByRole("button", { name: "Uppdatera secret" });
    update.focus();
    fireEvent.click(update);

    expect(document.activeElement).toBe(field(dialog, /^Ny Client Secret/));
    fireEvent.change(field(dialog, /^Ny Client Secret/), { target: { value: "hemlis-3" } });
    field(dialog, /^Bekräfta klienthemlighet/).focus();
    fireEvent.change(field(dialog, /^Bekräfta klienthemlighet/), {
      target: { value: "hemlis" }
    });
    fireEvent.blur(field(dialog, /^Bekräfta klienthemlighet/));

    const save = within(dialog).getByRole("button", { name: "Spara" }) as HTMLButtonElement;
    expect(within(dialog).getByText("Värdena matchar inte")).toBeTruthy();
    await expectNoAxeViolations(document.body);
    // Saving now moves focus to the problem, and sends nothing.
    fireEvent.click(save);
    expect(document.activeElement).toBe(field(dialog, /^Bekräfta klienthemlighet/));
    expect(api.POST).not.toHaveBeenCalled();

    fireEvent.change(field(dialog, /^Bekräfta klienthemlighet/), {
      target: { value: "hemlis-3" }
    });
    fireEvent.click(save);
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/sharepoint/app", {
        body: {
          client_id: "c0ffee",
          client_secret: "hemlis-3",
          tenant_domain: "sundsvall.onmicrosoft.com"
        }
      })
    );

    fireEvent.click(within(dialog).getByRole("button", { name: "Tillbaka" }));
    expect(within(dialog).queryByLabelText(/^Ny Client Secret/)).toBeNull();
    expect(document.activeElement).toBe(
      within(dialog).getByRole("button", { name: "Uppdatera secret" })
    );
  });
});
