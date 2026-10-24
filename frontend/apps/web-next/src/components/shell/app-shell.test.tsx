// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router, setRoute } from "@/test/navigation";
import { renderInApp, renderToHtml, testAppContext, testQueryClient } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { AppShellFrame } from "./app-shell";
import { OPEN_NAV_EVENT } from "./routes";
import { OWN_MOBILE_HEADER } from "./shell-context";

vi.mock("next/navigation", () => import("@/test/navigation"));
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

function seededClient() {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces"], []);
  queryClient.setQueryData(["dashboard"], { spaces: { items: [] } });
  return queryClient;
}

function renderShellWith(page: React.ReactNode, appContext = testAppContext()) {
  return renderInApp(<AppShellFrame>{page}</AppShellFrame>, {
    queryClient: seededClient(),
    appContext
  });
}

function renderShell() {
  return renderShellWith(<h1>Sidinnehåll</h1>);
}

beforeEach(() => setRoute("/spaces/list"));
afterEach(cleanup);

describe("AppShellFrame", () => {
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
    setRoute("/admin/users");
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
    renderShellWith(<h1>Sidinnehåll</h1>, testAppContext({ permissions: ["shared_spaces"] }));
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
  beforeEach(() => setViewport("phone"));

  it("gives way to a page's own header in CSS, already in the server render", () => {
    // No state and no route list: the top bar is in every render and the
    // frame's :has() hides it while the page carries OWN_MOBILE_HEADER, so it
    // is right before hydration, while a page streams in and when a chat
    // fails. jsdom applies no stylesheet; tests/shell-headers.spec.ts checks
    // what users see.
    setRoute("/spaces/s1/chat");
    const html = renderToHtml(
      <AppShellFrame>
        <div {...OWN_MOBILE_HEADER} />
      </AppShellFrame>,
      { queryClient: seededClient() }
    );
    const doc = new DOMParser().parseFromString(html, "text/html");
    const topBar = doc.querySelector("header");
    expect(topBar?.className).toContain("group-has-[[data-own-mobile-header]]/shell:hidden");
    // A space's header replaces it on phones only (OWN_PHONE_HEADER).
    expect(topBar?.className).toContain("max-md:group-has-[[data-own-phone-header]]/shell:hidden");
    expect(
      topBar?.closest('[class~="group/shell"]')?.querySelector("[data-own-mobile-header]")
    ).toBeTruthy();
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
    setRoute("/spaces/s1/chat");
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

  it("opens search from the top bar", async () => {
    renderShell();
    const topBar = screen.getByRole("banner");
    fireEvent.click(within(topBar).getByRole("button", { name: "Sök" }));
    expect(await screen.findByRole("dialog", { name: "Sök i Eneo" })).toBeTruthy();
  });

  it("closes the drawer when the palette opens a result on the same page", async () => {
    setRoute("/spaces/personal/chat");
    renderShell();
    const menuButton = screen.getByRole("button", { name: "Öppna menyn" });
    fireEvent.click(menuButton);
    const drawer = await screen.findByRole("dialog", { name: "Meny" });

    // "Sök" in the drawer opens the palette over it.
    fireEvent.click(within(drawer).getByRole("button", { name: "Sök" }));
    const palette = await screen.findByRole("dialog", { name: "Sök i Eneo" });
    fireEvent.click(await within(palette).findByRole("option", { name: /Ny konversation/ }));

    // Same path, so no pathname change closes the drawer: the palette does.
    expect(router.push).toHaveBeenCalledWith("/spaces/personal/chat");
    await waitFor(() => expect(menuButton.getAttribute("aria-expanded")).toBe("false"));
  });
});

describe("AppShellFrame on an iPad", () => {
  it("uses the drawer held upright and the SideNav sideways", () => {
    setViewport("tablet-portrait");
    renderShell();
    expect(screen.getByRole("button", { name: "Öppna menyn" })).toBeTruthy();

    act(() => setViewport("tablet-landscape"));
    expect(screen.queryByRole("button", { name: "Öppna menyn" })).toBeNull();
  });

  it("closes the open drawer when the iPad turns sideways and hands focus to the page", async () => {
    setViewport("tablet-portrait");
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Öppna menyn" }));
    const drawer = await screen.findByRole("dialog", { name: "Meny" });
    within(drawer).getByRole("link", { name: "Alla ytor" }).focus();

    act(() => setViewport("tablet-landscape"));
    expect(screen.queryByRole("dialog", { name: "Meny" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("main"));
  });

  it("leaves focus alone on first paint", () => {
    setViewport("tablet-landscape");
    renderShell();
    expect(document.activeElement).toBe(document.body);
  });
});
