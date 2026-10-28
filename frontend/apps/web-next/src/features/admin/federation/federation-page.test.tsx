// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import type { FederationView } from "./federation";

const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

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

/** What Astryx's polite live region says now. */
const announced = () =>
  document.querySelector('[data-astryx-live-region="polite"]')?.textContent ?? "";

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

  it.each([
    ["not configured", () => ok({ ...view, configured: false, revision: null })],
    [
      "federation disabled",
      () =>
        refused(404, {
          code: "federation_disabled",
          message: "Federation is not enabled on this installation."
        })
    ]
  ])("%s: tells the admin the operator connects the IdP and shows no form", async (_, read) => {
    api.GET.mockImplementation(read);
    const { container } = renderInApp(<FederationPage />);

    await screen.findByText("Ingen identitetsleverantör är inkopplad");
    expect(screen.getByText(/kopplar in organisationens identitetsleverantör/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Spara ändringar" })).toBeNull();
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
    await expectNoAxeViolations(dialog);

    fireEvent.click(within(dialog).getByRole("button", { name: "Spara och använd" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/admin/federation", {
      body: { revision: "rev-1", client_id: "next-client" }
    });
    expect(clientId().value).toBe("next-client");
    // Nothing left to save: Save stays focusable and asks nothing.
    fireEvent.click(save());
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(api.PATCH).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(announced()).toBe("Inloggningsinställningarna är sparade."));
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
    expect(screen.getByText(/ser ut som en maskerad hemlighet/)).toBeTruthy();
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
