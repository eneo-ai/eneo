// @vitest-environment jsdom
import { SideNav } from "@astryxdesign/core/SideNav";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { setRoute } from "@/test/navigation";
import { noopShell, renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { spaceQueryOptions, spacesListQueryOptions, type Space } from "../space";
import { makeSpace } from "../testing/space-fixture";
import {
  SpaceNavHeading,
  SpaceNavSections,
  SpacesListNavHeading,
  SpacesListNavSections
} from "./space-nav";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const SHARED = makeSpace({ overrides: { id: "s1", name: "Upphandling" } });
const OTHER = makeSpace({ overrides: { id: "s2", name: "Socialtjänst" } });
const PERSONAL = makeSpace({
  permissions: ["read"],
  overrides: {
    id: "p",
    name: "Personal",
    personal: true,
    members: { items: [], count: 0, permissions: [] }
  }
});
const ORG = makeSpace({ overrides: { id: "o", name: "Org", organization: true } });

function client(spaces: Record<string, Space | undefined>) {
  const queryClient = testQueryClient();
  for (const [routeId, space] of Object.entries(spaces)) {
    if (space) queryClient.setQueryData(spaceQueryOptions(browserApi, routeId).queryKey, space);
  }
  queryClient.setQueryData(spacesListQueryOptions(browserApi).queryKey, [
    SHARED,
    OTHER,
    PERSONAL,
    ORG
  ]);
  return queryClient;
}

function renderNav(
  route: string,
  {
    spaces = { s1: SHARED, personal: PERSONAL, organization: ORG } as Record<
      string,
      Space | undefined
    >,
    permissions = ["shared_spaces"] as Permission[],
    list = false,
    queryClient = client(spaces)
  } = {}
) {
  setRoute(route);
  const shell = { ...noopShell, openCreateSpace: vi.fn() };
  const utils = renderInApp(
    <SideNav
      aria-label="Ytans navigering"
      header={list ? <SpacesListNavHeading /> : <SpaceNavHeading />}
    >
      {list ? <SpacesListNavSections /> : <SpaceNavSections />}
    </SideNav>,
    { queryClient, appContext: testAppContext({ permissions }), shell }
  );
  return { ...utils, shell, queryClient };
}

const links = () =>
  screen.getAllByRole("link").map((link) => ({
    name: link.textContent,
    href: link.getAttribute("href"),
    current: link.getAttribute("aria-current") === "page"
  }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SpaceNav", () => {
  it("lists a shared space's sections in Svelte's order, marking the current one", () => {
    renderNav("/spaces/s1/knowledge");
    expect(links()).toEqual([
      { name: "Översikt", href: "/spaces/s1/overview", current: false },
      { name: "Assistenter", href: "/spaces/s1/assistants", current: false },
      { name: "Appar", href: "/spaces/s1/apps", current: false },
      { name: "Kunskap", href: "/spaces/s1/knowledge", current: true },
      { name: "Skills", href: "/spaces/s1/skills", current: false },
      { name: "Medlemmar", href: "/spaces/s1/members", current: false },
      { name: "Inställningar", href: "/spaces/s1/settings", current: false }
    ]);
    // A divider before Medlemmar, as in SpaceMenu.svelte.
    expect(screen.getAllByRole("separator")).toHaveLength(1);
  });

  it("starts the personal space with Chatt under a fixed heading", () => {
    renderNav("/spaces/personal/chat");
    expect(screen.getByText("Personlig yta")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Öppna meny/ })).toBeNull();
    expect(links()[0]).toEqual({
      name: "Chatt",
      href: "/spaces/personal/chat?tab=chat",
      current: true
    });
  });

  it("marks Assistenter, not Chatt, on a chat with an assistant", () => {
    renderNav("/spaces/personal/chat?type=assistant&id=a1");
    const current = links().filter((link) => link.current);
    expect(current.map((link) => link.name)).toEqual(["Assistenter"]);
  });

  it("gives the organisation space a fixed heading and its sections", () => {
    renderNav("/spaces/organization/knowledge");
    expect(screen.getByText("Organisationsyta")).toBeTruthy();
    expect(links().map((link) => link.name)).toEqual(["Kunskap", "Skills", "Inställningar"]);
  });

  it("switches between shared spaces and creates one from the heading's menu", () => {
    const { shell } = renderNav("/spaces/s1/overview");
    fireEvent.click(screen.getByRole("button", { name: "Öppna meny" }));
    const items = screen.getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Dina ytor",
      "Upphandling",
      "Socialtjänst",
      "Skapa en ny yta"
    ]);
    expect(items[1]?.getAttribute("aria-current")).toBe("true");
    expect(items[2]?.getAttribute("href")).toBe("/spaces/s2/overview");
    fireEvent.click(items[3]!);
    expect(shell.openCreateSpace).toHaveBeenCalled();
  });

  it("moves one row per arrow key, however many handlers Astryx stacks", () => {
    renderNav("/spaces/s1/overview");
    fireEvent.click(screen.getByRole("button", { name: "Öppna meny" }));
    const [yours, current, other] = screen.getAllByRole("menuitem");
    yours!.focus();
    fireEvent.keyDown(yours!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(current);
    fireEvent.keyDown(current!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(other);
  });

  it("keeps Dina ytor and Skapa en ny yta outside the spaces' scroll area", () => {
    renderNav("/spaces/s1/overview");
    fireEvent.click(screen.getByRole("button", { name: "Öppna meny" }));
    const scroll = screen.getByRole("menuitem", { name: "Socialtjänst" }).parentElement!;
    expect(scroll.className).toMatch(/(^| )max-h-\[50dvh\]( |$)/);
    expect(scroll.className).toMatch(/(^| )overflow-y-auto( |$)/);
    expect(scroll.contains(screen.getByRole("menuitem", { name: "Dina ytor" }))).toBe(false);
    expect(scroll.contains(screen.getByRole("menuitem", { name: "Skapa en ny yta" }))).toBe(false);
  });

  it("closes on a pick, in the full sidebar too, where the heading stays mounted", () => {
    const proto = HTMLElement.prototype as Partial<HTMLElement>;
    const hidePopover = vi.fn();
    proto.hidePopover = hidePopover;
    try {
      renderNav("/spaces/s1/overview");
      fireEvent.click(screen.getByRole("button", { name: "Öppna meny" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "Socialtjänst" }));
      expect(hidePopover).toHaveBeenCalled();
    } finally {
      delete proto.hidePopover;
    }
  });

  it("mounts a row per space only once the switcher opens, where popovers are native", () => {
    // A browser with the Popover API: opening fires beforetoggle on the menu's popover.
    const proto = HTMLElement.prototype as Partial<HTMLElement>;
    proto.showPopover = function (this: HTMLElement) {
      this.dispatchEvent(Object.assign(new Event("beforetoggle"), { newState: "open" }));
    };
    proto.hidePopover = () => {};
    try {
      renderNav("/spaces/s1/overview");
      expect(screen.queryByText("Socialtjänst")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Öppna meny" }));
      expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual([
        "Dina ytor",
        "Upphandling",
        "Socialtjänst",
        "Skapa en ny yta"
      ]);
    } finally {
      delete proto.showPopover;
      delete proto.hidePopover;
    }
  });

  it("offers Skapa en ny yta only with the shared_spaces permission", () => {
    renderNav("/spaces/s1/overview", { permissions: [] });
    fireEvent.click(screen.getByRole("button", { name: "Öppna meny" }));
    expect(screen.queryByRole("menuitem", { name: "Skapa en ny yta" })).toBeNull();
  });

  it("shows the classification under the space's name", () => {
    const classified = makeSpace({
      overrides: {
        id: "s1",
        name: "Upphandling",
        security_classification: {
          id: "c1",
          name: "Intern",
          security_level: 1
        } as Space["security_classification"]
      }
    });
    renderNav("/spaces/s1/overview", { spaces: { s1: classified } });
    // The closed menu repeats the heading (Astryx mounts it eagerly).
    expect(screen.getAllByText("Intern").length).toBeGreaterThan(0);
  });

  it("shows a skeleton while the space loads, then its sections", () => {
    renderNav("/spaces/s9/overview", { spaces: {} });
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("offers a retry when the route could not load the space", async () => {
    const queryClient = client({});
    vi.spyOn(browserApi, "GET").mockRejectedValue(new Error("boom"));
    // The route's loader fetched it and failed; the sidebar only reads that.
    await queryClient.query(spaceQueryOptions(browserApi, "s9")).catch(() => {});
    renderNav("/spaces/s9/overview", { queryClient });
    expect(await screen.findByRole("button", { name: "Försök ladda ytorna igen" })).toBeTruthy();
  });

  it("never requests the space itself: the route's loader owns that", () => {
    const get = vi.spyOn(browserApi, "GET");
    renderNav("/spaces/s9/overview", { spaces: {} });
    expect(get).not.toHaveBeenCalledWith("/api/v1/spaces/{id}/", expect.anything());
  });

  it("keeps the cached sections when a background refresh fails", async () => {
    const { queryClient } = renderNav("/spaces/s1/overview");
    const get = vi.spyOn(browserApi, "GET").mockRejectedValue(new Error("boom"));
    // A page's own reader refreshes the cached space and fails.
    await act(async () => {
      await queryClient
        .query({ ...spaceQueryOptions(browserApi, "s1"), staleTime: 0, retry: false })
        .catch(() => {});
      // Let Query notify the sidebar of the failure before looking at it.
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(get).toHaveBeenCalled();
    expect(queryClient.getQueryState(spaceQueryOptions(browserApi, "s1").queryKey)?.status).toBe(
      "error"
    );
    expect(links().map((link) => link.name)).toContain("Översikt");
    expect(screen.queryByRole("button", { name: "Försök ladda ytorna igen" })).toBeNull();
  });

  it("drops a cached space once it is gone (404)", async () => {
    const { queryClient } = renderNav("/spaces/s1/overview");
    vi.spyOn(browserApi, "GET").mockRejectedValue(new EneoApiError("Missing", { status: 404 }));
    await act(() =>
      queryClient
        .query({ ...spaceQueryOptions(browserApi, "s1"), staleTime: 0, retry: false })
        .catch(() => {})
    );
    await waitFor(() => expect(screen.queryAllByRole("link")).toHaveLength(0));
    expect(screen.queryByText("Upphandling")).toBeNull();
  });

  it("shows Välj en yta and Dina ytor on the spaces list", () => {
    renderNav("/spaces/list", { list: true });
    expect(screen.getAllByText("Välj en yta").length).toBeGreaterThan(0);
    expect(links()).toEqual([{ name: "Dina ytor", href: "/spaces/list", current: true }]);
  });

  it("has no axe violations", async () => {
    const { container } = renderNav("/spaces/s1/overview");
    await expectNoAxeViolations(container);
  });
});
