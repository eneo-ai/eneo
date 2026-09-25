// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { AppShellFrame } from "./app-shell";
import { conversationHref, OPEN_NAV_EVENT } from "./routes";
import { useShell } from "./shell-context";
import { resetSideNavCollapsedForTest } from "./shell-state";
import { installBrowserMocks, renderWithProviders, testQueryClient } from "./test-support";

const nav = vi.hoisted(() => ({ pathname: "/spaces/list", search: "" }));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(nav.search),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() })
}));
vi.mock("@/features/jobs/job-indicator", () => ({ JobIndicator: () => null }));
vi.mock("@/features/api-keys/expiring-keys-notification", () => ({
  ExpiringKeysNotification: () => null
}));
vi.mock("@/features/whats-new/whats-new-provider", () => ({
  useWhatsNew: () => ({ enabled: false, hasUnseen: false })
}));
vi.mock("@/lib/i18n/actions", () => ({ setLocale: vi.fn() }));

function renderShellWith(page: React.ReactNode) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces"], []);
  queryClient.setQueryData(["dashboard"], { spaces: { items: [] } });
  return renderWithProviders(<AppShellFrame>{page}</AppShellFrame>, { queryClient });
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
  window.localStorage.clear();
  resetSideNavCollapsedForTest();
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

  it("opens the drawer when the chat's header asks for it", async () => {
    nav.pathname = "/spaces/s1/chat";
    renderShell();
    act(() => {
      window.dispatchEvent(new CustomEvent(OPEN_NAV_EVENT));
    });
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "Meny" }).hasAttribute("open")).toBe(true)
    );
  });
});

describe("page remount for same-page conversation links", () => {
  beforeEach(() => installBrowserMocks());

  let mounts = 0;
  function ChatProbe() {
    const [mount] = useState(() => ++mounts);
    const { prepareNavigation } = useShell();
    return (
      <button type="button" onClick={() => prepareNavigation(conversationHref("b"))}>
        {`mount ${mount}`}
      </button>
    );
  }

  function goTo(search: string) {
    nav.search = search;
    window.history.replaceState(null, "", `${nav.pathname}?${search}`);
  }

  it("starts the page afresh when a shell link opens another conversation here", () => {
    mounts = 0;
    nav.pathname = "/spaces/personal/chat";
    goTo("session_id=a");
    // A new element each time, so the frame re-reads the (mocked) router.
    const shell = () => (
      <AppShellFrame>
        <ChatProbe />
      </AppShellFrame>
    );
    const { rerender } = renderWithProviders(shell());
    expect(screen.getByRole("button", { name: "mount 1" })).toBeTruthy();

    // The chat updating its own URL keeps the page mounted.
    goTo("session_id=a2");
    rerender(shell());
    expect(screen.getByRole("button", { name: "mount 1" })).toBeTruthy();

    // A shell link to another conversation remounts once the URL arrives.
    fireEvent.click(screen.getByRole("button", { name: "mount 1" }));
    goTo("session_id=b");
    rerender(shell());
    expect(screen.getByRole("button", { name: "mount 2" })).toBeTruthy();
  });
});
