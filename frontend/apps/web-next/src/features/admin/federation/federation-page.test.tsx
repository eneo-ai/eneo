// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import type { FederationView } from "./federation";

const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

import { FederationPage } from "./federation-page";

const SECRET = "tenant-new-secret-Zq7x";

const view: FederationView = {
  configured: true,
  provider: "Entra ID",
  discovery_endpoint: "https://idp.example/.well-known/openid-configuration",
  issuer: "https://idp.example",
  client_id: "eneo-client",
  client_secret_set: true,
  client_secret_updated_at: "2026-10-01T08:00:00Z",
  encryption_status: "encrypted",
  allowed_domains: ["sundsvall.se"],
  redirect_uris: ["https://eneo.example/login/callback", "https://alt.eneo.example/login/callback"],
  redirect_uris_problem: null,
  scopes: ["openid", "email", "profile"],
  token_endpoint_auth_method: "client_secret_post",
  revision: "rev-1",
  configured_at: "2026-10-01T08:00:00Z"
};

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
const refused = (status: number, body: unknown) =>
  Promise.resolve({ error: body, response: new Response(null, { status }) });

/** What Astryx's polite live region says now; messages close together are joined. */
const announced = () =>
  document.querySelector('[data-astryx-live-region="polite"]')?.textContent ?? "";
/** Text shown on the page, not only in the live region. */
const shown = (text: string) =>
  screen.queryByText(text, { ignore: "script, style, [data-astryx-live-region]" });

afterEach(() => {
  vi.clearAllMocks();
  document
    .querySelectorAll("[data-astryx-live-region]")
    .forEach((region) => (region.textContent = ""));
});

async function show(current: FederationView = view) {
  api.GET.mockImplementation(() => ok(current));
  const queryClient = testQueryClient();
  const result = renderInApp(<FederationPage />, { queryClient });
  await screen.findByLabelText(/Klient-ID/);
  return { ...result, queryClient };
}

const clientId = () => screen.getByLabelText(/Klient-ID/) as HTMLInputElement;
const save = () => screen.getByRole("button", { name: "Spara ändringar" });

describe("states", () => {
  it("shows the skeleton while loading", async () => {
    api.GET.mockImplementation(() => new Promise(() => {}));
    renderInApp(<FederationPage />);

    expect(screen.getByRole("status").textContent).toContain("Hämtar inloggningsinställningarna…");
    expect(screen.getByRole("heading", { level: 1, name: "Inloggning (SSO)" })).toBeTruthy();
  });

  it("reports a failed read with a retry", async () => {
    api.GET.mockImplementationOnce(() => refused(500, { message: "boom", eneo_error_code: 9024 }));
    api.GET.mockImplementation(() => ok(view));
    renderInApp(<FederationPage />);

    const retry = await screen.findByRole("button", { name: /Försök igen/ });
    expect(retry.closest('[role="alert"]')?.textContent).toContain(
      "Inloggningsinställningarna kunde inte hämtas"
    );
    fireEvent.click(retry);
    await screen.findByLabelText(/Klient-ID/);
  });

  it("not configured: tells the admin the operator connects the IdP and shows no form", async () => {
    api.GET.mockImplementation(() => ok({ ...view, configured: false, revision: null }));
    const { container } = renderInApp(<FederationPage />);

    await screen.findByText("Ingen identitetsleverantör är inkopplad");
    expect(screen.getByText(/kopplar in organisationens identitetsleverantör/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Spara ändringar" })).toBeNull();
    const guide = screen.getByRole("link", {
      name: new RegExp(sv.federation_admin_register_guide_link)
    });
    expect(guide.getAttribute("href")).toContain(
      "/sv/guides/oidc-federation/single-tenant#configure-via-api"
    );
    // A stand-alone link: a touch-sized row of its own (the contract measures it on the screen).
    expect(guide.className).toContain("pointer-coarse:min-h-11");
    await expectNoAxeViolations(container);
  });

  it("settings kept in the server configuration: says who manages them and shows no form", async () => {
    api.GET.mockImplementation(() =>
      refused(404, {
        code: "federation_disabled",
        message: "Federation is not enabled on this installation."
      })
    );
    const { container } = renderInApp(<FederationPage />);

    await screen.findByText(sv.federation_admin_disabled_title);
    expect(screen.getByText(sv.federation_admin_disabled_description)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Spara ändringar" })).toBeNull();
    const guide = screen.getByRole("link", { name: new RegExp(sv.federation_admin_guide_link) });
    expect(guide.getAttribute("href")).toContain(
      "/sv/guides/oidc-federation/single-tenant#move-the-settings-into-eneo"
    );
    expect(guide.textContent).toContain(sv.chat_opens_in_new_tab);
    expect(guide.className).toContain("pointer-coarse:min-h-11");
    await expectNoAxeViolations(container);
  });
});

describe("the settings", () => {
  it("shows operator-owned values as text and the secret only as saved", async () => {
    const { container } = await show();

    const discovery = screen.getByText(view.discovery_endpoint!);
    expect(discovery.closest("dd")).toBeTruthy();
    expect(discovery.closest("a")).toBeNull();
    expect(screen.getByText(/^Sparad /)).toBeTruthy();
    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(
      screen.getByRole("heading", { level: 2, name: "Inställningar ni kan ändra" })
    ).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("copies a redirect URI from a button named by it, and announces it", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await show();

    fireEvent.click(
      screen.getByRole("button", { name: "Kopiera https://alt.eneo.example/login/callback" })
    );

    await waitFor(() => expect(announced()).toBe("Kopierat till urklipp"));
    expect(writeText).toHaveBeenCalledWith("https://alt.eneo.example/login/callback");
  });
});

describe("saving", () => {
  it("confirms exactly the change, then shows the saved settings without a reload", async () => {
    api.PATCH.mockImplementation(() =>
      ok({ ...view, client_id: "next-client", revision: "rev-2" })
    );
    await show();

    fireEvent.change(clientId(), { target: { value: "next-client" } });
    fireEvent.click(save());

    const dialog = await screen.findByRole("alertdialog", {
      name: "Ändra inloggningen för hela organisationen?"
    });
    const changes = within(dialog)
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(changes).toEqual(["Klient-ID: eneo-client → next-client"]);
    expect(dialog.textContent).toContain(sv.federation_admin_confirm_client_id);
    await expectNoAxeViolations(dialog);

    fireEvent.click(within(dialog).getByRole("button", { name: "Spara och använd" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/admin/federation", {
      body: { revision: "rev-1", client_id: "next-client" }
    });
    expect(clientId().value).toBe("next-client");
    await waitFor(() => expect(announced()).toContain("Inloggningsinställningarna är sparade."));
    // Nothing left to save: Save stays focusable, asks nothing and says so. That
    // announcement replaces the previous one, so each is checked after its own action.
    fireEvent.click(save());
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(api.PATCH).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(announced()).toBe(sv.federation_admin_nothing_to_save));
  });

  it("warns about existing accounts only when the client ID changes", async () => {
    await show();

    fireEvent.change(screen.getByLabelText(/Tillåtna e-postdomäner/), {
      target: { value: "example.org" }
    });
    fireEvent.click(save());

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).not.toContain(sv.federation_admin_confirm_client_id);
  });

  it("cannot be closed with Escape while saving", async () => {
    let finish: (value: unknown) => void = () => {};
    api.PATCH.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
    await show();
    fireEvent.change(clientId(), { target: { value: "next-client" } });
    fireEvent.click(save());
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara och använd" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalled());

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("alertdialog")).toBeTruthy();

    await act(async () =>
      finish({ data: { ...view, revision: "rev-2" }, response: new Response("{}") })
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it.each([
    ["an empty client ID", () => clientId(), "", "Detta fält är obligatoriskt"],
    [
      "an invalid domain",
      () => screen.getByLabelText(/Tillåtna e-postdomäner/),
      "sundsvall.se\nnot_a_domain",
      "”not_a_domain” är inte en giltig domän"
    ]
  ])("explains %s at the field and moves focus there", async (_, field, value, message) => {
    const { container } = await show();

    fireEvent.change(field(), { target: { value } });
    fireEvent.click(save());

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(field().getAttribute("aria-invalid")).toBe("true");
    expect(container.textContent).toContain(message);
    expect(document.activeElement).toBe(field());
    expect(api.PATCH).not.toHaveBeenCalled();
    await expectNoAxeViolations(container);
  });

  it("keeps a replaced secret out of the DOM and the caches after saving", async () => {
    api.PATCH.mockImplementation(() =>
      ok({ ...view, client_secret_updated_at: "2026-10-28T09:00:00Z", revision: "rev-2" })
    );
    const { container, queryClient } = await show();

    fireEvent.click(screen.getByRole("button", { name: "Byt hemlighet" }));
    const input = screen.getByLabelText(/Klienthemlighet/) as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(input.value).toBe("");
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: SECRET } });
    fireEvent.click(save());
    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual(["Klienthemligheten byts ut"]);
    expect(dialog.textContent).toContain(sv.federation_admin_confirm_secret);
    expect(dialog.textContent).not.toContain(SECRET);
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara och använd" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/admin/federation", {
      body: { revision: "rev-1", client_secret: SECRET }
    });
    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(document.body.innerHTML).not.toContain(SECRET);
    const cached = JSON.stringify([
      queryClient
        .getQueryCache()
        .getAll()
        .map((query) => query.state),
      queryClient
        .getMutationCache()
        .getAll()
        .map((mutation) => mutation.state)
    ]);
    expect(cached).not.toContain(SECRET);
  });

  it("keeps focus on the page after a secret saved from its field with Enter", async () => {
    api.PATCH.mockImplementation(() => ok({ ...view, revision: "rev-2" }));
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Byt hemlighet" }));
    const input = screen.getByLabelText(/Klienthemlighet/);
    fireEvent.change(input, { target: { value: SECRET } });
    expect(document.activeElement).toBe(input);
    fireEvent.submit(input.closest("form")!);
    fireEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Spara och använd"
      })
    );

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Byt hemlighet" }))
    );
  });

  it("says in its own words why a secret cannot be stored", async () => {
    api.PATCH.mockImplementation(() =>
      refused(503, {
        code: "federation_encryption_unavailable",
        message: "Encryption is not configured, so a client secret cannot be stored."
      })
    );
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Byt hemlighet" }));
    fireEvent.change(screen.getByLabelText(/Klienthemlighet/), { target: { value: SECRET } });
    fireEvent.click(save());
    fireEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Spara och använd"
      })
    );

    const alert = (await screen.findByText(/kryptering inte är konfigurerad/)).closest(
      '[role="alert"]'
    );
    expect(alert?.textContent).not.toContain("Encryption is not configured");
  });

  it("shows a masked-looking secret's refusal at the secret", async () => {
    api.PATCH.mockImplementation(() =>
      refused(400, { code: "federation_secret_looks_masked", message: "masked" })
    );
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Byt hemlighet" }));
    fireEvent.change(screen.getByLabelText(/Klienthemlighet/), {
      target: { value: "********" }
    });
    fireEvent.click(save());
    fireEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Spara och använd"
      })
    );

    const secret = screen.getByLabelText(/Klienthemlighet/);
    await waitFor(() => expect(secret.getAttribute("aria-invalid")).toBe("true"));
    await waitFor(() => expect(announced()).toContain(sv.federation_admin_secret_masked));
    const describedBy = (secret.getAttribute("aria-describedby") ?? "")
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ");
    expect(describedBy).toContain(sv.federation_admin_secret_masked);
  });

  it("reports another admin's save, and Reload loads their values", async () => {
    api.PATCH.mockImplementation(() =>
      refused(409, {
        code: "federation_config_revision_conflict",
        message: "The sign-in settings changed after you loaded them."
      })
    );
    const { container } = await show();
    fireEvent.change(clientId(), { target: { value: "mine" } });
    fireEvent.click(save());
    fireEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Spara och använd"
      })
    );

    const banner = await screen.findByText("Någon annan har ändrat inställningarna");
    expect(clientId().value).toBe("mine");
    await expectNoAxeViolations(container);
    // A failed reload keeps the draft and the banner ...
    api.GET.mockImplementation(() => refused(500, { message: "boom", eneo_error_code: 9024 }));
    fireEvent.click(screen.getByRole("button", { name: "Ladda om" }));
    await waitFor(() => expect(api.GET).toHaveBeenCalledTimes(2));
    await screen.findByText(/Innehållet kunde inte uppdateras/);
    expect(clientId().value).toBe("mine");
    expect(banner.isConnected).toBe(true);

    // ... and a successful one loads the other admin's values.
    api.GET.mockImplementation(() => ok({ ...view, client_id: "theirs", revision: "rev-2" }));
    fireEvent.click(screen.getByRole("button", { name: "Ladda om" }));
    await waitFor(() => expect(clientId().value).toBe("theirs"));
    expect(banner.isConnected).toBe(false);
    expect(screen.queryByText("Någon annan har ändrat inställningarna")).toBeNull();
  });
});

it("has every text in Swedish and English", () => {
  const keys = (catalog: Record<string, string>) =>
    Object.keys(catalog).filter((key) => key.startsWith("federation_admin_"));
  expect(keys(sv).length).toBeGreaterThan(30);
  expect(keys(en)).toEqual(keys(sv));
  for (const key of keys(en)) expect((en as Record<string, string>)[key]).toBeTruthy();
});

describe("account creation at first sign-in", () => {
  it.each([
    [false, "federation_admin_jit_off"],
    [true, "federation_admin_jit_on"]
  ] as const)(
    "with automatic account creation %s it says what happens to people without an account",
    async (provisioning, key) => {
      api.GET.mockImplementation(() => ok(view));
      renderInApp(<FederationPage />, {
        appContext: testAppContext({ settings: { provisioning } })
      });

      const domains = await screen.findByLabelText(sv.federation_admin_domains);
      expect(domains.getAttribute("aria-describedby")).toBeTruthy();
      const describedBy = domains
        .getAttribute("aria-describedby")!
        .split(" ")
        .map((id) => document.getElementById(id)?.textContent)
        .join(" ");
      expect(describedBy).toContain(sv[key]);
      const link = screen.getByRole("link", {
        name: `Ändra under ${sv.enable_provisioning}`
      });
      expect(link.getAttribute("href")).toBe("/admin/settings");
    }
  );

  it("with automatic account creation and an empty list it says no accounts are created", async () => {
    api.GET.mockImplementation(() => ok(view));
    renderInApp(<FederationPage />, {
      appContext: testAppContext({ settings: { provisioning: true } })
    });

    const domains = await screen.findByLabelText(sv.federation_admin_domains);
    fireEvent.change(domains, { target: { value: "" } });
    expect(await screen.findByText(sv.federation_admin_jit_no_domains)).toBeTruthy();
  });
});

describe("before and after a save", () => {
  const listed: FederationView = { ...view, allowed_domains: ["example.org", "example.com"] };
  const provider = () => screen.getByLabelText(new RegExp(sv.federation_admin_provider_label));
  const domains = () => screen.getByLabelText(new RegExp(sv.federation_admin_domains));
  const description = (field: HTMLElement) =>
    (field.getAttribute("aria-describedby") ?? "")
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ");
  const items = (dialog: HTMLElement) =>
    within(dialog)
      .getAllByRole("listitem")
      .map((item) => item.textContent);
  const confirm = async () =>
    fireEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: sv.federation_admin_confirm_action
      })
    );

  it("explains the name and the client ID at their fields", async () => {
    await show();

    expect(description(provider())).toContain(sv.federation_admin_provider_help);
    expect(description(clientId())).toContain(sv.federation_admin_client_id_help);
  });

  it("names what is not saved, and Undo restores the saved values", async () => {
    await show();

    fireEvent.change(clientId(), { target: { value: "next-client" } });
    const unsaved = sv.federation_admin_unsaved.replace("{fields}", sv.client_id);
    expect(shown(unsaved)).toBeTruthy();
    await waitFor(() => expect(announced()).toBe(unsaved));

    fireEvent.click(screen.getByRole("button", { name: sv.federation_admin_undo }));

    expect(clientId().value).toBe("eneo-client");
    expect(document.activeElement).toBe(save());
    expect(shown(unsaved)).toBeNull();
    expect(screen.queryByRole("button", { name: sv.federation_admin_undo })).toBeNull();
  });

  it("says so when Save has nothing to save", async () => {
    await show();

    fireEvent.click(save());

    expect(shown(sv.federation_admin_nothing_to_save)).toBeTruthy();
    await waitFor(() => expect(announced()).toBe(sv.federation_admin_nothing_to_save));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.change(clientId(), { target: { value: "next-client" } });
    expect(shown(sv.federation_admin_nothing_to_save)).toBeNull();
  });

  it("confirms a new name calmly, without the sign-in warning", async () => {
    await show();

    fireEvent.change(provider(), { target: { value: "Okta" } });
    fireEvent.click(save());

    const dialog = await screen.findByRole("alertdialog", {
      name: sv.federation_admin_confirm_label_title
    });
    expect(dialog.textContent).toContain(sv.federation_admin_confirm_label_description);
    expect(dialog.textContent).not.toContain(sv.federation_admin_confirm_recovery);
  });

  it("lists the domains added and removed, and what each change does to sign-in", async () => {
    await show(listed);

    fireEvent.change(domains(), { target: { value: "example.com\nfoo.se" } });
    fireEvent.click(save());

    const dialog = await screen.findByRole("alertdialog", {
      name: sv.federation_admin_confirm_title
    });
    const added = sv.federation_admin_domains_added.replace("{domains}", "foo.se");
    const removed = sv.federation_admin_domains_removed.replace("{domains}", "example.org");
    expect(items(dialog)).toEqual([`${sv.federation_admin_domains}: ${added}; ${removed}`]);
    expect(dialog.textContent).toContain(
      sv.federation_admin_confirm_domains_removed.replace("{domains}", "example.org")
    );
    expect(dialog.textContent).toContain(
      sv.federation_admin_confirm_domains_added.replace("{domains}", "foo.se")
    );
    expect(dialog.textContent).toContain(sv.federation_admin_confirm_recovery);
    await expectNoAxeViolations(dialog);
  });

  it("after a change to who can sign in, suggests trying it before signing out", async () => {
    api.PATCH.mockImplementation(() =>
      ok({ ...view, client_id: "next-client", revision: "rev-2" })
    );
    await show();

    fireEvent.change(clientId(), { target: { value: "next-client" } });
    fireEvent.click(save());
    await confirm();

    expect(await screen.findByText(sv.federation_admin_saved_next_step)).toBeTruthy();
    await waitFor(() =>
      expect(announced()).toContain(
        `${sv.federation_admin_saved} ${sv.federation_admin_saved_next_step}`
      )
    );
    fireEvent.change(clientId(), { target: { value: "again" } });
    expect(screen.queryByText(sv.federation_admin_saved_next_step)).toBeNull();
  });

  it("a new name is saved without the suggestion", async () => {
    api.PATCH.mockImplementation(() => ok({ ...view, provider: "Okta", revision: "rev-2" }));
    await show();

    fireEvent.change(provider(), { target: { value: "Okta" } });
    fireEvent.click(save());
    await confirm();

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(screen.queryByText(sv.federation_admin_saved_next_step)).toBeNull();
    await waitFor(() => expect(announced()).toContain(sv.federation_admin_saved));
    expect(announced()).not.toContain(sv.federation_admin_saved_next_step);
  });
});
