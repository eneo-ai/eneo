// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { setRoute } from "@/test/navigation";
import { noopShell, renderInApp, testAppContext } from "@/test/render";
import { TopBar } from "./top-bar";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/jobs/job-indicator", () => ({ JobIndicator: () => null }));
vi.mock("@/features/api-keys/expiring-keys-notification", () => ({
  ExpiringKeysNotification: () => null
}));
vi.mock("@/features/whats-new/whats-new-provider", () => ({
  useWhatsNew: () => ({ enabled: false, hasUnseen: false })
}));

function renderBar({ route = "/spaces/personal/chat", permissions = [] as Permission[] } = {}) {
  setRoute(route);
  const shell = { ...noopShell, openPalette: vi.fn() };
  const utils = renderInApp(<TopBar />, { appContext: testAppContext({ permissions }), shell });
  return { ...utils, shell };
}

function areas() {
  return screen.getByRole("navigation", { name: "Huvudområden" });
}

function current() {
  return (
    within(areas())
      .getAllByRole("link")
      // The current area, not the current page: that stays the page's own link.
      .filter((link) => link.getAttribute("aria-current") === "true")
      .map((link) => link.textContent)
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("TopBar", () => {
  it("links the areas where Svelte's top bar does", () => {
    renderBar({ permissions: ["admin"] });
    const nav = areas();
    const href = (name: string) => within(nav).getByRole("link", { name }).getAttribute("href");

    expect(href("Personligt")).toBe("/spaces/personal/chat");
    expect(href("Delat")).toBe("/spaces/list");
    expect(href("Organisation")).toBe("/spaces/organization/knowledge");
    expect(href("Administratör")).toBe("/admin");
    expect(screen.getByRole("link", { name: "Eneo, till startsidan" }).getAttribute("href")).toBe(
      "/"
    );
  });

  it("shows Organisation and Administratör to admins only", () => {
    renderBar();
    const nav = areas();
    expect(within(nav).getByRole("link", { name: "Personligt" })).toBeTruthy();
    expect(within(nav).getByRole("link", { name: "Delat" })).toBeTruthy();
    expect(within(nav).queryByRole("link", { name: "Organisation" })).toBeNull();
    expect(within(nav).queryByRole("link", { name: "Administratör" })).toBeNull();
  });

  it.each([
    ["/spaces/personal/chat", "Personligt"],
    ["/spaces/personal/overview", "Personligt"],
    ["/spaces/list", "Delat"],
    ["/spaces/s1/assistants", "Delat"],
    ["/spaces/organization/knowledge", "Organisation"],
    ["/admin/models", "Administratör"]
  ])("marks the area of %s as current", (route, area) => {
    renderBar({ route, permissions: ["admin"] });
    expect(current()).toEqual([area]);
  });

  it("marks no area outside spaces and admin", () => {
    renderBar({ route: "/account", permissions: ["admin"] });
    expect(current()).toEqual([]);
  });

  it("opens the command palette from Sök and advertises the shortcut", () => {
    const { shell } = renderBar();
    const search = screen.getByRole("button", { name: "Sök" });
    expect(search.getAttribute("aria-keyshortcuts")).toBe("Meta+K Control+K");
    fireEvent.click(search);
    expect(shell.openPalette).toHaveBeenCalledTimes(1);
  });

  it("hides and shows again, by keyboard too", () => {
    renderBar();
    const hide = screen.getByRole("button", { name: "Dölj sidhuvudet" });
    act(() => hide.focus());
    fireEvent.click(hide);

    // Hidden: out of the tab order and the accessibility tree, the show button takes focus.
    expect(screen.queryByRole("navigation", { name: "Huvudområden" })).toBeNull();
    const show = screen.getByRole("button", { name: "Visa sidhuvudet" });
    expect(document.activeElement).toBe(show);

    fireEvent.click(show);
    expect(areas()).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Dölj sidhuvudet" }));
  });

  it("shows again when the pointer reaches the top edge", () => {
    const { container } = renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Dölj sidhuvudet" }));
    fireEvent.pointerEnter(container.querySelector("[data-top-bar-reveal]")!);
    expect(areas()).toBeTruthy();
  });

  it("has no axe violations", async () => {
    const { container } = renderBar({ permissions: ["admin"] });
    await expectNoAxeViolations(container);
  });
});
