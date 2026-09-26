// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { AppShellFrame } from "./app-shell";
import { OPEN_NAV_EVENT } from "./routes";
import {
  appContext,
  installBrowserMocks,
  renderWithProviders,
  testQueryClient
} from "./test-support";

const nav = vi.hoisted(() => ({ pathname: "/spaces/list", search: "" }));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(nav.search),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() })
}));
// Stand-ins that show where the bells are placed (they have their own tests).
vi.mock("@/features/jobs/job-indicator", () => ({
  JobIndicator: () => <button type="button">Jobbklockan</button>
}));
vi.mock("@/features/api-keys/expiring-keys-notification", () => ({
  ExpiringKeysNotification: () => null
}));
vi.mock("@/features/whats-new/whats-new-provider", () => ({
  useWhatsNew: () => ({ enabled: false, hasUnseen: false })
}));
vi.mock("@/lib/i18n/actions", () => ({ setLocale: vi.fn() }));

function renderShellWith(page: React.ReactNode, context = appContext()) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces"], []);
  queryClient.setQueryData(["dashboard"], { spaces: { items: [] } });
  return renderWithProviders(<AppShellFrame>{page}</AppShellFrame>, { queryClient, context });
}

function renderShell() {
  return renderShellWith(<h1>Sidinnehåll</h1>);
}

beforeEach(() => {
  nav.pathname = "/spaces/list";
  nav.search = "";
});

afterEach(() => {
  cleanup();
});

describe("AppShellFrame", () => {
  beforeEach(() => installBrowserMocks());

  it("puts the skip link first and the page in main#main-content", async () => {
    const { container } = renderShell();
    const focusable = container.querySelectorAll<HTMLElement>(
      "a[href], button:not([disabled]), input, [tabindex]:not([tabindex='-1'])"
    );
    const skip = screen.getByRole("link", { name: "Hoppa till innehåll" });
    expect(focusable[0]).toBe(skip);
    expect(skip.getAttribute("href")).toBe("#main-content");

    const main = screen.getByRole("main");
    expect(main.id).toBe("main-content");
    expect(main.getAttribute("tabindex")).toBe("-1");
    expect(within(main).getByRole("heading", { name: "Sidinnehåll" })).toBeTruthy();
    expect(screen.getAllByRole("main")).toHaveLength(1);
    await expectNoAxeViolations(container);
  });

  it("switches the SideNav to admin mode under /admin", () => {
    nav.pathname = "/admin/users";
    renderShell();
    expect(screen.getByRole("navigation", { name: "Administration" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "Huvudmeny" })).toBeNull();
  });

  it("opens the command palette with Ctrl+K", async () => {
    renderShell();
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }));
    });
    const dialog = await screen.findByRole("dialog", { name: "Sök i Eneo" });
    expect(
      within(dialog).getByRole("combobox", {
        name: "Sök bland assistenter, ytor, konversationer, kunskap och åtgärder"
      })
    ).toBeTruthy();

    // Ctrl+K from the palette's own search field closes it again.
    fireEvent.keyDown(within(dialog).getByRole("combobox"), { key: "k", ctrlKey: true });
    await waitFor(() => expect(dialog.hasAttribute("open")).toBe(false));
  });

  it("leaves Ctrl+K alone while the user types in a field", () => {
    renderShellWith(<textarea aria-label="Meddelande" />);
    const field = screen.getByRole("textbox", { name: "Meddelande" });
    const event = new KeyboardEvent("keydown", {
      key: "k",
      ctrlKey: true,
      bubbles: true,
      cancelable: true
    });
    act(() => {
      field.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(false);
    expect(screen.queryByRole("dialog", { name: "Sök i Eneo" })).toBeNull();
  });

  it("opens the app's one create-space dialog from the SideNav", async () => {
    renderShellWith(<h1>Sidinnehåll</h1>, appContext({ permissions: ["shared_spaces"] }));
    // The form exists only while the dialog is open: no stray Namn field.
    expect(screen.queryByLabelText(/Namn/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Skapa yta" }));

    const dialog = await screen.findByRole("dialog", { name: "Skapa en ny yta" });
    expect(within(dialog).getByLabelText(/Namn/)).toBeTruthy();
  });

  it("does not open the palette over another dialog", () => {
    renderShellWith(
      <dialog open aria-label="Bekräfta">
        …
      </dialog>
    );
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }));
    });
    expect(screen.queryByRole("dialog", { name: "Sök i Eneo" })).toBeNull();
  });
});

describe("AppShellFrame on a phone", () => {
  beforeEach(() => installBrowserMocks({ mobile: true }));

  it("renders the mobile top bar except on chat routes, which have their own header", () => {
    renderShell();
    expect(screen.getByRole("button", { name: "Öppna menyn" })).toBeTruthy();
    cleanup();

    nav.pathname = "/spaces/personal/chat";
    renderShell();
    expect(screen.queryByRole("button", { name: "Öppna menyn" })).toBeNull();
  });

  it("opens the drawer from the top bar and closes it with Escape", async () => {
    renderShell();
    const menuButton = screen.getByRole("button", { name: "Öppna menyn" });
    expect(menuButton.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(menuButton);

    const drawer = await screen.findByRole("dialog", { name: "Meny" });
    expect(menuButton.getAttribute("aria-expanded")).toBe("true");
    expect(menuButton.getAttribute("aria-controls")).toBe(drawer.id);
    expect(within(drawer).getByRole("navigation", { name: "Huvudmeny" })).toBeTruthy();
    await expectNoAxeViolations(document.body);

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(menuButton.getAttribute("aria-expanded")).toBe("false"));
  });

  it("opens the drawer when the chat's header asks for it, with the bells in it", async () => {
    nav.pathname = "/spaces/s1/chat";
    renderShell();
    // Chat routes have no top bar: the drawer is where the bells are.
    act(() => {
      window.dispatchEvent(new CustomEvent(OPEN_NAV_EVENT));
    });
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "Meny" }).hasAttribute("open")).toBe(true)
    );
    const drawer = screen.getByRole("dialog", { name: "Meny" });
    expect(within(drawer).getByRole("button", { name: "Jobbklockan" })).toBeTruthy();
  });
});
