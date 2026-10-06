// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

import { SharePointAppConfigDialog } from "./sharepoint-app-config-dialog";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const configured = {
  id: "app-1",
  tenant_id: "tenant-1",
  client_id: "c0ffee",
  client_secret_masked: "****a1b2",
  tenant_domain: "sundsvall.onmicrosoft.com",
  is_active: true,
  auth_method: "service_account",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z"
};

async function renderDialog(config: typeof configured | null) {
  api.GET.mockImplementation(() => ok(config));
  renderInApp(
    <SharePointAppConfigDialog open onOpenChange={() => {}} onRequestDelete={() => {}} />
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
