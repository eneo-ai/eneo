import { page, userEvent, type Locator } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, describe, expect, test, vi, type MockInstance } from "vitest";
import "../../../../app.css";

const invalidate = vi.hoisted(() => vi.fn(async () => {}));
const assignLocation = vi.hoisted(() => vi.fn());
const readFederation = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  disableScrollHandling: vi.fn(),
  goto: vi.fn(),
  invalidate,
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadCode: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  refreshAll: vi.fn(),
  replaceState: vi.fn()
}));
// The action answers are plain JSON here; the real wire format is devalue.
vi.mock("$app/forms", () => ({ deserialize: (text: string) => JSON.parse(text) }));
vi.mock("$lib/core/navigation", () => ({ assignLocation }));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({ federation: { get: readFederation } }) }));
vi.mock("$lib/components/toast", () => ({ toast: { success: toastSuccess, error: vi.fn() } }));
vi.mock("$lib/paraglide/runtime", () => ({ getLocale: () => "en" }));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, unknown>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)} ${JSON.stringify(params)}` : String(key)
    }
  )
}));

import FederationPage from "./+page.svelte";

const SECRET = "s3cret-value-never-shown";

const view = {
  configured: true,
  provider: "Entra ID",
  discovery_endpoint: "https://idp.example/.well-known/openid-configuration",
  issuer: "https://idp.example",
  client_id: "client-a",
  client_secret_set: true,
  client_secret_updated_at: "2026-11-01T10:00:00Z",
  encryption_status: "encrypted",
  allowed_domains: ["example.com"],
  redirect_uris: ["https://eneo.example/login/callback"],
  scopes: ["openid", "email", "profile"],
  token_endpoint_auth_method: "client_secret_post",
  revision: "rev-1"
};

type State =
  | { kind: "ready"; view: typeof view }
  | { kind: "unconfigured" }
  | { kind: "disabled" }
  | { kind: "error" };

function show(state: State | Promise<State>) {
  return render(FederationPage, {
    data: { federation: Promise.resolve(state) }
  } as never);
}

function answer(result: unknown) {
  return new Response(JSON.stringify(result), { headers: { "content-type": "application/json" } });
}

let fetchSpy: MockInstance<typeof fetch>;

function sentForm(call = 0): [string, FormDataEntryValue][] {
  const init = fetchSpy.mock.calls[call][1];
  return [...(init?.body as FormData).entries()];
}

// The page header overlaps the form in the test viewport, so clicks go to the element.
async function press(locator: Locator) {
  await expect.element(locator).toBeVisible();
  (locator.element() as HTMLElement).click();
}

const field = (name: string) => page.getByLabelText(name, { exact: true });
const confirmButton = () => page.getByRole("button", { name: "federation_admin_confirm_action" });

/** Confirms like a person: only once the open dialog has taken focus (a frame after opening). */
async function confirmSave() {
  await vi.waitFor(() => {
    if (!document.querySelector("[role=alertdialog]")?.contains(document.activeElement)) {
      throw new Error("The dialog has not taken focus yet");
    }
  });
  await press(confirmButton());
}

async function requestSave() {
  await press(page.getByRole("button", { name: "save_changes" }));
}

async function changeDomains(text: string) {
  await userEvent.fill(field("federation_admin_domains"), text);
}

beforeEach(() => {
  invalidate.mockClear();
  assignLocation.mockClear();
  toastSuccess.mockClear();
  readFederation.mockReset();
  fetchSpy = vi.spyOn(globalThis, "fetch");
});

afterEach(() => {
  fetchSpy.mockRestore();
});

describe("the page's states", () => {
  test("shows a loading state while the settings are read", async () => {
    render(FederationPage, { data: { federation: new Promise(() => {}) } } as never);
    await expect.element(page.getByLabelText("federation_admin_loading")).toBeVisible();
  });

  test("without stored settings it explains who manages sign-in and links the guide", async () => {
    show({ kind: "disabled" });

    await expect.element(page.getByText("federation_admin_disabled_description")).toBeVisible();
    const guide = page.getByRole("link", { name: /federation_admin_guide_link/ });
    await expect
      .element(guide)
      .toHaveAttribute("href", expect.stringContaining("/guides/oidc-federation/single-tenant#"));
    expect(page.getByRole("button", { name: "save_changes" }).elements()).toHaveLength(0);
    expect(document.activeElement).toBe(document.body);
  });

  test("an organisation without a provider is told so, without a form, with the operator's guide", async () => {
    show({ kind: "unconfigured" });

    await expect.element(page.getByText("federation_admin_not_configured_title")).toBeVisible();
    expect(page.getByRole("button", { name: "save_changes" }).elements()).toHaveLength(0);
    await expect
      .element(page.getByRole("link", { name: /federation_admin_register_guide_link/ }))
      .toHaveAttribute("href", expect.stringContaining("#configure-via-api"));
  });

  test("a failed read can be retried", async () => {
    show({ kind: "error" });

    await press(page.getByRole("button", { name: "retry" }));
    expect(invalidate).toHaveBeenCalledWith("admin:federation");
  });

  test("shows what the operator owns as text, with a named copy button per redirect URI", async () => {
    show({ kind: "ready", view: { ...view, encryption_status: "plaintext" } });

    await expect.element(page.getByText(view.discovery_endpoint)).toBeVisible();
    await expect.element(page.getByText(view.issuer, { exact: true })).toBeVisible();
    expect(page.getByRole("link", { name: view.discovery_endpoint }).elements()).toHaveLength(0);
    await expect
      .element(
        page.getByRole("button", {
          name: `federation_admin_copy_uri {"uri":"${view.redirect_uris[0]}"}`
        })
      )
      .toBeVisible();
    await expect.element(page.getByText("federation_admin_secret_plaintext")).toBeVisible();
    await expect.element(field("client_id")).toHaveValue("client-a");
    expect(document.querySelector("input[type=password]")).toBeNull();
  });

  test("announces which redirect URI was copied, also right after another", async () => {
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    const uris = ["https://eneo.example/login/callback", "https://eneo.example/other/callback"];
    show({ kind: "ready", view: { ...view, redirect_uris: uris } });

    for (const uri of uris) {
      await press(page.getByRole("button", { name: `federation_admin_copy_uri {"uri":"${uri}"}` }));
      await expect
        .element(page.getByText(`federation_admin_uri_copied {"uri":"${uri}"}`))
        .toBeInTheDocument();
    }
    expect(writeText).toHaveBeenLastCalledWith(uris[1]);
    writeText.mockRestore();
  });

  test("explains the name, the client ID and the stored secret before anything is saved", async () => {
    show({ kind: "ready", view });

    await expect
      .element(field("federation_admin_provider_label"))
      .toHaveAccessibleDescription(/federation_admin_provider_help/);
    await expect
      .element(field("client_id"))
      .toHaveAccessibleDescription(/federation_admin_client_id_help/);
    await expect
      .element(page.getByRole("button", { name: "federation_admin_secret_replace" }))
      .toHaveAccessibleDescription(/federation_admin_secret_saved/);
  });
});

describe("saving", () => {
  test("a refused value is explained at its field before anything is sent", async () => {
    show({ kind: "ready", view });

    await userEvent.fill(field("federation_admin_provider_label"), " ");
    await requestSave();

    const provider = field("federation_admin_provider_label");
    await expect.element(provider).toHaveFocus();
    await expect.element(provider).toHaveAttribute("aria-invalid", "true");
    await expect.element(provider).toHaveAccessibleDescription(/required_field/);
    expect(confirmButton().elements()).toHaveLength(0);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("a risky change is confirmed once, sent once and becomes the new base", async () => {
    let respond!: (response: Response) => void;
    fetchSpy.mockImplementationOnce(() => new Promise((resolve) => (respond = resolve)));
    show({ kind: "ready", view });

    await changeDomains("example.com\nexample.org");
    await requestSave();

    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog).toHaveTextContent("federation_admin_confirm_title");
    // The domains the save adds, not two whole lists, and what that means.
    await expect.element(dialog).toHaveTextContent(/federation_admin_domains_added.*example\.org/);
    await expect
      .element(dialog)
      .toHaveTextContent(/federation_admin_confirm_domains_added.*example\.org/);
    await expect.element(dialog).toHaveTextContent("federation_admin_confirm_recovery");
    await expect.element(confirmButton()).toHaveClass(/text-destructive/);
    await confirmSave();
    await expect.element(page.getByRole("button", { name: "saving" })).toBeVisible();
    (page.getByRole("button", { name: "saving" }).element() as HTMLElement).click();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(sentForm()).toEqual([
      ["revision", "rev-1"],
      ["allowed_domains", "example.com\nexample.org"]
    ]);
    expect(fetchSpy.mock.calls[0][1]?.headers).toMatchObject({ "x-sveltekit-action": "true" });

    respond(
      answer({
        type: "success",
        status: 200,
        data: {
          view: { ...view, allowed_domains: ["example.com", "example.org"], revision: "rev-2" }
        }
      })
    );

    await expect.element(dialog).not.toBeInTheDocument();
    expect(toastSuccess).toHaveBeenCalledWith("federation_admin_saved");
    await expect.element(page.getByRole("button", { name: "save_changes" })).toHaveFocus();
    // After a change to who can sign in, the next step is to try it.
    await expect.element(page.getByText("federation_admin_saved_next_step")).toBeVisible();

    fetchSpy.mockResolvedValueOnce(
      answer({ type: "success", status: 200, data: { view: { ...view, revision: "rev-3" } } })
    );
    await userEvent.fill(field("client_id"), "client-b");
    await requestSave();
    await confirmSave();
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    expect(sentForm(1)).toEqual([
      ["revision", "rev-2"],
      ["client_id", "client-b"]
    ]);
  });

  test("starting a new secret after a save ends the suggestion to try sign-in", async () => {
    fetchSpy.mockResolvedValueOnce(
      answer({
        type: "success",
        status: 200,
        data: {
          view: { ...view, allowed_domains: ["example.com", "example.org"], revision: "rev-2" }
        }
      })
    );
    show({ kind: "ready", view });

    await changeDomains("example.com\nexample.org");
    await requestSave();
    await confirmSave();
    await expect.element(page.getByText("federation_admin_saved_next_step")).toBeVisible();

    await press(page.getByRole("button", { name: "federation_admin_secret_replace" }));
    await expect
      .element(page.getByText("federation_admin_saved_next_step"))
      .not.toBeInTheDocument();
  });

  test("renaming the provider is a plain confirmation, and cancelling sends nothing", async () => {
    show({ kind: "ready", view });

    await userEvent.fill(field("federation_admin_provider_label"), "Okta");
    await requestSave();
    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog).toHaveTextContent("federation_admin_confirm_label_title");
    await expect.element(dialog).not.toHaveTextContent("federation_admin_confirm_title");
    await expect.element(dialog).not.toHaveTextContent("federation_admin_confirm_recovery");
    await expect.element(confirmButton()).toHaveClass(/bg-accent-default/);
    await press(page.getByRole("button", { name: "cancel" }));

    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("only a new client ID warns about existing accounts", async () => {
    show({ kind: "ready", view });

    await userEvent.fill(field("client_id"), "client-b");
    await requestSave();
    await expect
      .element(page.getByRole("alertdialog"))
      .toHaveTextContent(/federation_admin_confirm_client_id/);
    await press(page.getByRole("button", { name: "cancel" }));
    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();

    await userEvent.fill(field("client_id"), "client-a");
    await changeDomains("example.org");
    await requestSave();
    await expect.element(page.getByRole("alertdialog")).toBeVisible();
    await expect
      .element(page.getByRole("alertdialog"))
      .not.toHaveTextContent(/federation_admin_confirm_client_id/);
  });

  test("an unchanged form has nothing to confirm, and says so", async () => {
    show({ kind: "ready", view });

    await requestSave();

    expect(confirmButton().elements()).toHaveLength(0);
    await expect.element(page.getByText("federation_admin_nothing_to_save")).toBeVisible();
  });

  test("unsaved changes are named next to Save and can be undone", async () => {
    show({ kind: "ready", view });

    await userEvent.fill(field("client_id"), "client-b");
    await expect
      .element(page.getByText('federation_admin_unsaved {"fields":"client_id"}'))
      .toBeVisible();

    await press(page.getByRole("button", { name: "federation_admin_undo" }));

    await expect.element(field("client_id")).toHaveValue("client-a");
    await expect.element(page.getByRole("button", { name: "save_changes" })).toHaveFocus();
    expect(page.getByRole("button", { name: "federation_admin_undo" }).elements()).toHaveLength(0);
    expect(page.getByText(/federation_admin_unsaved/).elements()).toHaveLength(0);
  });
});

describe("the client secret", () => {
  test("is never shown; replacing it opens an empty field, keeping it closes the field", async () => {
    show({ kind: "ready", view });

    await press(page.getByRole("button", { name: "federation_admin_secret_replace" }));
    const secret = field("client_secret");
    await expect.element(secret).toHaveFocus();
    await expect.element(secret).toHaveValue("");
    await expect.element(secret).toHaveAttribute("type", "password");
    await expect.element(secret).toHaveAttribute("autocomplete", "new-password");

    await press(page.getByRole("button", { name: "federation_admin_secret_keep" }));
    expect(document.querySelector("input[type=password]")).toBeNull();
    await expect
      .element(page.getByRole("button", { name: "federation_admin_secret_replace" }))
      .toHaveFocus();
  });

  test("a new secret is sent but never shown in the confirmation", async () => {
    fetchSpy.mockResolvedValueOnce(
      answer({ type: "success", status: 200, data: { view: { ...view, revision: "rev-2" } } })
    );
    show({ kind: "ready", view });

    await press(page.getByRole("button", { name: "federation_admin_secret_replace" }));
    await userEvent.fill(field("client_secret"), SECRET);
    await requestSave();

    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog).toHaveTextContent("federation_admin_secret_replaced_change");
    await expect.element(dialog).toHaveTextContent("federation_admin_confirm_secret");
    expect(dialog.element().textContent).not.toContain(SECRET);
    await confirmSave();

    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    expect(sentForm()).toEqual([
      ["revision", "rev-1"],
      ["client_secret", SECRET]
    ]);
    await vi.waitFor(() => expect(document.querySelector("input[type=password]")).toBeNull());
  });

  test("an empty new secret is explained at the field", async () => {
    show({ kind: "ready", view });

    await press(page.getByRole("button", { name: "federation_admin_secret_replace" }));
    await requestSave();

    const secret = field("client_secret");
    await expect.element(secret).toHaveFocus();
    await expect.element(secret).toHaveAccessibleDescription(/federation_admin_secret_required/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("a refused secret is reported at the field, which is emptied and focused", async () => {
    fetchSpy.mockResolvedValueOnce(
      answer({
        type: "failure",
        status: 400,
        data: { failure: { code: "fields", fields: { client_secret: "secret_masked" } } }
      })
    );
    show({ kind: "ready", view });

    await press(page.getByRole("button", { name: "federation_admin_secret_replace" }));
    await userEvent.fill(field("client_secret"), "********");
    await requestSave();
    await confirmSave();

    const secret = field("client_secret");
    await expect.element(secret).toHaveFocus();
    await expect.element(secret).toHaveValue("");
    await expect.element(secret).toHaveAccessibleDescription(/federation_admin_secret_masked/);
  });
});

describe("refused saves", () => {
  async function saveDomainChange(result: unknown) {
    fetchSpy.mockResolvedValueOnce(answer(result));
    show({ kind: "ready", view });
    await changeDomains("example.org");
    await requestSave();
    await confirmSave();
  }

  test("after a conflict the admin reloads the other admin's values and continues from them", async () => {
    readFederation.mockResolvedValueOnce({ ...view, provider: "Okta", revision: "rev-9" });
    await saveDomainChange({
      type: "failure",
      status: 409,
      data: { failure: { code: "conflict" } }
    });

    const conflict = page.getByRole("alert").filter({ hasText: "federation_admin_conflict_title" });
    await expect.element(conflict).toHaveFocus();
    await press(page.getByRole("button", { name: "federation_admin_conflict_reload" }));

    const provider = field("federation_admin_provider_label");
    await expect.element(provider).toHaveValue("Okta");
    await expect.element(provider).toHaveFocus();
    await expect.element(field("federation_admin_domains")).toHaveValue("example.com");
    expect(page.getByText("federation_admin_conflict_title").elements()).toHaveLength(0);
  });

  test("a failed reload keeps what the admin typed", async () => {
    readFederation.mockRejectedValueOnce(new Error("offline"));
    await saveDomainChange({
      type: "failure",
      status: 409,
      data: { failure: { code: "conflict" } }
    });

    await press(page.getByRole("button", { name: "federation_admin_conflict_reload" }));

    await expect.element(page.getByText("federation_admin_load_error")).toBeVisible();
    await expect.element(field("federation_admin_domains")).toHaveValue("example.org");
  });

  test("a refused value from the server is reported at its field", async () => {
    await saveDomainChange({
      type: "failure",
      status: 422,
      data: { failure: { code: "fields", fields: { allowed_domains: "refused" } } }
    });

    const domains = field("federation_admin_domains");
    await expect.element(domains).toHaveFocus();
    await expect.element(domains).toHaveAccessibleDescription(/federation_admin_field_refused/);
  });

  test("a save the server cannot store is a focused form error", async () => {
    await saveDomainChange({
      type: "failure",
      status: 503,
      data: { failure: { code: "encryption_unavailable" } }
    });

    const error = page
      .getByRole("alert")
      .filter({ hasText: "federation_admin_encryption_unavailable" });
    await expect.element(error).toHaveFocus();
  });

  test("an unexpected answer is a focused form error", async () => {
    fetchSpy.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    show({ kind: "ready", view });
    await changeDomains("example.org");
    await requestSave();
    await confirmSave();

    const error = page.getByRole("alert").filter({ hasText: "federation_admin_save_error" });
    await expect.element(error).toHaveFocus();
  });

  test("settings that are gone make the page read them again", async () => {
    await saveDomainChange({
      type: "failure",
      status: 404,
      data: { failure: { code: "not_configured" } }
    });

    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith("admin:federation"));
  });

  test("when sign-in moved back to the server configuration, focus follows to the explanation", async () => {
    fetchSpy.mockResolvedValueOnce(
      answer({ type: "failure", status: 404, data: { failure: { code: "disabled" } } })
    );
    const screen = show({ kind: "ready", view });
    invalidate.mockImplementationOnce(async () => {
      await screen.rerender({
        data: { federation: Promise.resolve({ kind: "disabled" }) }
      } as never);
    });
    await changeDomains("example.org");
    await requestSave();
    await confirmSave();

    await expect.element(page.getByText("federation_admin_disabled_title")).toBeVisible();
    await vi.waitFor(() => {
      expect(document.activeElement).not.toBe(document.body);
      expect(document.activeElement?.textContent).toContain("federation_admin_disabled_title");
    });
  });

  test("an expired session follows the redirect to sign in", async () => {
    await saveDomainChange({ type: "redirect", status: 303, location: "/login?next=%2Fadmin" });

    await vi.waitFor(() => expect(assignLocation).toHaveBeenCalledWith("/login?next=%2Fadmin"));
  });
});
