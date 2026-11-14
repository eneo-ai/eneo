// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { spaceQueryOptions } from "@/features/spaces/space";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { recentConversationsQueryOptions, type RecentConversation } from "@/lib/api/conversations";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { setRoute } from "@/test/navigation";
import { noopShell, renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { PHONE_VIEWPORT, setViewport } from "@/test/setup-dom";
import type { NavVariant } from "./routes";
import { SideNav } from "@astryxdesign/core/SideNav";
import { MainSections, MainTopContent } from "./main-nav";
import { NavFooter } from "./nav-footer";
import { NavHeader } from "./nav-header";
import { DesktopSideNav, useSideNavRail } from "./side-nav";
import { SIDE_NAV_COLLAPSED_COOKIE } from "./side-nav-preference";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/jobs/job-indicator", () => ({ JobIndicator: () => null }));
vi.mock("@/features/api-keys/expiring-keys-notification", () => ({
  ExpiringKeysNotification: () => null
}));
vi.mock("@/features/whats-new/whats-new-provider", () => ({
  useWhatsNew: () => ({ enabled: false, hasUnseen: false })
}));

/**
 * The SideNav as the app shell renders it (the shell owns its rail state).
 * Beside the top bar the admin pages have the admin nav; the main navigation
 * (Ny konversation, the spaces, Senaste) is the phone drawer's, rendered here
 * in a SideNav of the same make so its content and the rail can be tested.
 */
function SpaceSideNav() {
  return <DesktopSideNav kind="space" navId="side-nav" rail={useSideNavRail(undefined)} />;
}

function RailedSideNav({
  variant,
  navId,
  defaultCollapsed
}: {
  variant: NavVariant;
  navId: string;
  defaultCollapsed?: boolean;
}) {
  const rail = useSideNavRail(defaultCollapsed);
  if (variant === "admin") return <DesktopSideNav kind="admin" navId={navId} rail={rail} />;
  return (
    <SideNav
      id={navId}
      aria-label="Huvudmeny"
      collapsible={{
        isCollapsed: rail.collapsed,
        onCollapsedChange: rail.change,
        hasButton: false
      }}
      header={<NavHeader navId={navId} />}
      topContent={<MainTopContent />}
      footer={<NavFooter variant="main" />}
    >
      <MainSections />
    </SideNav>
  );
}

const SPACES = [
  { id: "s1", name: "Upphandling", description: null, personal: false, organization: false },
  { id: "s2", name: "Socialtjänst", description: null, personal: false, organization: false },
  { id: "org", name: "Organisation", description: null, personal: false, organization: true }
];

function conversation(
  id: string,
  name: string,
  partner: RecentConversation["partner"],
  space: RecentConversation["space"]
): RecentConversation {
  const at = "2026-09-26T10:00:00Z";
  return { id, name, created_at: at, last_activity_at: at, partner, space };
}

const PERSONAL_SPACE = { id: "p", name: "Personal", personal: true, organization: false };
const PERSONAL_CHAT = { type: "default-assistant", id: "d", name: "Eneo" } as const;

/** Latest first, across the personal chat, space assistants and group chats. */
const CONVERSATIONS = [
  conversation("c1", "Upphandlingsanalys mot LOU", PERSONAL_CHAT, PERSONAL_SPACE),
  conversation(
    "c2",
    "Sammanfatta KS-protokoll",
    { type: "assistant", id: "a1", name: "Avtalsgranskaren" },
    { id: "s1", name: "Upphandling", personal: false, organization: false }
  ),
  conversation(
    "c3",
    "Veckomöte",
    { type: "group-chat", id: "g1", name: "Inköpsrådet" },
    { id: "s2", name: "Socialtjänst", personal: false, organization: false }
  ),
  conversation(
    "c4",
    "Årsplanering",
    { type: "default-assistant", id: "od", name: "Organisationsassistenten" },
    { id: "org", name: "Organisation", personal: false, organization: true }
  ),
  conversation("c5", "Mötesanteckningar", PERSONAL_CHAT, PERSONAL_SPACE),
  // Past the nav's five: only the ⌘K palette offers it.
  conversation("c6", "Gammal fråga", PERSONAL_CHAT, PERSONAL_SPACE)
];

function seededClient({ conversations = CONVERSATIONS } = {}) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces"], SPACES);
  queryClient.setQueryData(recentConversationsQueryOptions(browserApi).queryKey, conversations);
  return queryClient;
}

function renderNav({
  variant = "main" as NavVariant,
  permissions = [] as Permission[],
  conversations = CONVERSATIONS,
  shell = { ...noopShell, openPalette: vi.fn(), openCreateSpace: vi.fn() }
} = {}) {
  const utils = renderInApp(<RailedSideNav variant={variant} navId="side-nav" />, {
    queryClient: seededClient({ conversations }),
    appContext: testAppContext({ permissions }),
    shell
  });
  return { ...utils, shell };
}

function currentLinks() {
  return screen.getAllByRole("link").filter((link) => link.getAttribute("aria-current") === "page");
}

/** The accessible description: the text of the elements aria-describedby names. */
function descriptionOf(element: HTMLElement) {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent)
    .join(" ");
}

beforeEach(() => setRoute("/spaces/personal/chat"));

afterEach(() => {
  cleanup();
  document.cookie = `${SIDE_NAV_COLLAPSED_COOKIE}=; max-age=0; path=/`;
  vi.restoreAllMocks();
});

describe("DesktopSideNav (main)", () => {
  it("is a named navigation landmark with the design's destinations", async () => {
    const { container } = renderNav();
    const navigation = screen.getByRole("navigation", { name: "Huvudmeny" });

    expect(
      within(navigation).getByRole("link", { name: "Ny konversation" }).getAttribute("href")
    ).toBe("/spaces/personal/chat");
    // Sök is the top bar's beside the SideNav (top-bar.tsx).
    expect(within(navigation).queryByRole("button", { name: "Sök" })).toBeNull();
    expect(within(navigation).getByRole("link", { name: "Assistenter" }).getAttribute("href")).toBe(
      "/dashboard"
    );

    // The areas in the top bar's order: Personligt, then Delat with the
    // shared spaces (not the organisation space) and Dina ytor last.
    expect(within(navigation).getByRole("link", { name: "Personligt" }).getAttribute("href")).toBe(
      "/spaces/personal/overview"
    );
    const spaces = within(navigation).getByRole("group", { name: "Delat" });
    const spaceLinks = within(spaces).getAllByRole("link");
    expect(spaceLinks.map((link) => link.getAttribute("href"))).toEqual([
      "/spaces/s1/overview",
      "/spaces/s2/overview",
      "/spaces/list"
    ]);
    for (const name of ["Upphandling", "Socialtjänst", "Dina ytor"]) {
      expect(within(spaces).getByRole("link", { name })).toBeTruthy();
    }

    // The five latest conversations, each opening its own chat.
    const recent = within(navigation).getByRole("group", { name: "Senaste" });
    expect(
      within(recent)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"))
    ).toEqual([
      "/spaces/personal/chat?session_id=c1",
      "/spaces/s1/chat?type=assistant&id=a1&session_id=c2",
      "/spaces/s2/chat?type=group-chat&id=g1&session_id=c3",
      "/spaces/organization/chat?session_id=c4",
      "/spaces/personal/chat?session_id=c5"
    ]);

    await expectNoAxeViolations(container);
  });

  it("says who a conversation is with where its title alone doesn't", async () => {
    const { container } = renderNav();
    const recent = screen.getByRole("group", { name: "Senaste" });

    // Titles stay the links' names; the partner and its space are their
    // descriptions (and tooltips). The personal chat needs neither.
    const personal = within(recent).getByRole("link", { name: "Upphandlingsanalys mot LOU" });
    expect(personal.hasAttribute("aria-describedby")).toBe(false);
    expect(
      descriptionOf(within(recent).getByRole("link", { name: "Sammanfatta KS-protokoll" }))
    ).toBe("Avtalsgranskaren i Upphandling");
    expect(descriptionOf(within(recent).getByRole("link", { name: "Veckomöte" }))).toBe(
      "Inköpsrådet i Socialtjänst"
    );
    expect(descriptionOf(within(recent).getByRole("link", { name: "Årsplanering" }))).toBe(
      "Organisationsassistenten i Organisation"
    );

    // Plain links: each is a keyboard stop of its own.
    for (const link of within(recent).getAllByRole("link")) {
      link.focus();
      expect(document.activeElement).toBe(link);
    }
    await expectNoAxeViolations(container);
  });

  it("puts who a recent conversation is with into its label on a touch screen, which has no tooltip", () => {
    // A 13" iPad held sideways: wide enough for the full nav with nothing stored.
    setViewport({ ...PHONE_VIEWPORT, width: 1366, height: 1024 });
    renderNav();
    const recent = screen.getByRole("group", { name: "Senaste" });

    expect(
      within(recent).getByRole("link", {
        name: "Sammanfatta KS-protokoll · Avtalsgranskaren i Upphandling"
      })
    ).toBeTruthy();
    // The personal chat has no context to add.
    expect(within(recent).getByRole("link", { name: "Upphandlingsanalys mot LOU" })).toBeTruthy();
  });

  it("lists Organisation after Delat for admins, and leaves Administration and the profile to the top bar", () => {
    renderNav();
    expect(screen.queryByRole("link", { name: "Organisation" })).toBeNull();
    cleanup();
    renderNav({ permissions: ["admin"] });
    const organisation = screen.getByRole("link", { name: "Organisation" });
    expect(
      screen.getByRole("group", { name: "Delat" }).compareDocumentPosition(organisation) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    // With a mouse the top bar (top-bar.tsx) carries them beside the SideNav.
    expect(screen.queryByRole("link", { name: "Administration" })).toBeNull();
    expect(screen.queryByRole("button", { name: /konto och inställningar/ })).toBeNull();
  });

  it("marks the current page, one destination at a time", () => {
    renderNav();
    expect(screen.getByRole("link", { name: "Ny konversation" }).getAttribute("aria-current")).toBe(
      "page"
    );
    cleanup();

    setRoute("/spaces/personal/chat?session_id=c5");
    renderNav();
    expect(currentLinks()).toEqual([screen.getByRole("link", { name: "Mötesanteckningar" })]);
    cleanup();

    // A personal conversation Senaste doesn't show: nothing else stands in.
    setRoute("/spaces/personal/chat?session_id=c6");
    renderNav();
    expect(currentLinks()).toEqual([]);
    cleanup();

    setRoute("/spaces/s2/knowledge");
    renderNav();
    expect(currentLinks()).toEqual([screen.getByRole("link", { name: "Socialtjänst" })]);
  });

  it("marks a conversation of any assistant in Senaste, else its space", () => {
    setRoute("/spaces/s1/chat?type=assistant&id=a1&session_id=c2");
    renderNav();
    expect(currentLinks()).toEqual([
      screen.getByRole("link", { name: "Sammanfatta KS-protokoll" })
    ]);
    cleanup();

    // Past the five Senaste shows: the space it belongs to is current instead.
    setRoute("/spaces/s1/chat?type=assistant&id=a1&session_id=c9");
    renderNav();
    expect(currentLinks()).toEqual([screen.getByRole("link", { name: "Upphandling" })]);
    cleanup();

    // The organisation space's chat: Senaste, not Organisation, marks it.
    setRoute("/spaces/organization/chat?session_id=c4");
    renderNav({ permissions: ["admin"] });
    expect(currentLinks()).toEqual([screen.getByRole("link", { name: "Årsplanering" })]);
  });

  it("offers Skapa yta only with the shared-spaces permission", () => {
    renderNav();
    expect(screen.queryByRole("button", { name: "Skapa yta" })).toBeNull();
    cleanup();

    const { shell } = renderNav({ permissions: ["shared_spaces"] });
    fireEvent.click(screen.getByRole("button", { name: "Skapa yta" }));
    expect(shell.openCreateSpace).toHaveBeenCalledTimes(1);
  });

  it("hides Senaste when there are no conversations", () => {
    renderNav({ conversations: [] });
    expect(screen.queryByRole("group", { name: "Senaste" })).toBeNull();
  });

  it.each([false, true])(
    "shows a recoverable spaces error while keeping cached links (cached: %s)",
    async (cached) => {
      const queryClient = testQueryClient();
      queryClient.setQueryData(recentConversationsQueryOptions(browserApi).queryKey, CONVERSATIONS);
      if (cached) {
        queryClient.setQueryData(["spaces"], SPACES, { updatedAt: Date.now() - 60_000 });
      }

      let finishRetry: (() => void) | undefined;
      const retryResponse = new Promise((resolve) => {
        finishRetry = () =>
          resolve({
            data: { items: SPACES },
            error: undefined,
            response: new Response("{}", { status: 200 })
          });
      });
      let attempts = 0;
      vi.spyOn(browserApi, "GET").mockImplementation(((path: string) => {
        if (path !== "/api/v1/spaces/") throw new Error(`Unexpected request: ${path}`);
        attempts += 1;
        if (attempts === 1) return Promise.reject(new Error("offline"));
        return retryResponse;
      }) as unknown as typeof browserApi.GET);

      const { container } = renderInApp(<RailedSideNav variant="main" navId="side-nav" />, {
        queryClient
      });
      const spaces = within(screen.getByRole("navigation", { name: "Huvudmeny" })).getByRole(
        "group",
        { name: "Delat" }
      );
      expect(await within(spaces).findByText("Ytorna kunde inte laddas.")).toBeTruthy();
      expect(screen.getByRole("link", { name: "Personligt" })).toBeTruthy();
      expect(within(spaces).getByRole("link", { name: "Dina ytor" })).toBeTruthy();
      expect(Boolean(within(spaces).queryByRole("link", { name: "Upphandling" }))).toBe(cached);

      const retry = within(spaces).getByRole("button", { name: "Försök ladda ytorna igen" });
      retry.focus();
      fireEvent.click(retry);
      await waitFor(() => expect(retry.getAttribute("aria-busy")).toBe("true"));
      expect(document.activeElement).toBe(retry);
      expect(within(spaces).getByText("Ytorna kunde inte laddas.")).toBeTruthy();
      await act(async () => finishRetry?.());
      await waitFor(() => {
        expect(within(spaces).getByRole("link", { name: "Upphandling" })).toBeTruthy();
        expect(within(spaces).queryByText("Ytorna kunde inte laddas.")).toBeNull();
      });
      expect(document.activeElement).toBe(
        within(spaces).getByRole("link", { name: "Upphandling" })
      );
      await expectNoAxeViolations(container);
    }
  );

  it("collapses to an icon rail (disclosure) and remembers it", async () => {
    const { container } = renderNav();
    const collapse = screen.getByRole("button", { name: "Fäll ihop sidomenyn" });
    expect(collapse.getAttribute("aria-expanded")).toBe("true");
    expect(collapse.getAttribute("aria-controls")).toBe("side-nav");

    fireEvent.click(collapse);

    const expand = screen.getByRole("button", { name: "Fäll ut sidomenyn" });
    expect(expand.getAttribute("aria-expanded")).toBe("false");
    expect(document.cookie).toContain(`${SIDE_NAV_COLLAPSED_COOKIE}=1`);
    // Icon rail: titles-only rows (Senaste) and the section actions are gone,
    // icon rows keep their names.
    expect(screen.queryByRole("group", { name: "Senaste" })).toBeNull();
    expect(screen.getByRole("link", { name: "Upphandling" })).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(expand);
    expect(document.cookie).toContain(`${SIDE_NAV_COLLAPSED_COOKIE}=0`);
  });

  it("keeps focus on the toggle while it collapses and expands the nav", () => {
    renderNav();
    const toggle = screen.getByRole("button", { name: "Fäll ihop sidomenyn" });
    toggle.focus();

    fireEvent.click(toggle);
    // The same element, renamed: focus did not drop to <body> (WCAG 2.4.3).
    expect(screen.getByRole("button", { name: "Fäll ut sidomenyn" })).toBe(toggle);
    expect(document.activeElement).toBe(toggle);

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(toggle);
  });

  it("renders the stored preference on first mount", () => {
    // The route reads the stored cookie before mounting the nav.
    const { container } = renderInApp(
      <RailedSideNav variant="main" navId="side-nav" defaultCollapsed />,
      {
        queryClient: seededClient()
      }
    );
    expect(container.innerHTML).toContain('aria-label="Fäll ut sidomenyn"');
    expect(container.innerHTML).not.toContain("Fäll ihop sidomenyn");
  });
});

describe("DesktopSideNav on a tablet or a small laptop", () => {
  const expanded = () => screen.queryByRole("button", { name: "Fäll ihop sidomenyn" }) !== null;
  const renderStored = (defaultCollapsed?: boolean) =>
    renderInApp(
      <RailedSideNav variant="main" navId="side-nav" defaultCollapsed={defaultCollapsed} />,
      { queryClient: seededClient() }
    );

  it.each([
    ["an iPad held upright", "tablet-portrait"],
    ["an iPad held sideways", "tablet-landscape"]
  ] as const)("is an icon rail on %s when nothing is stored", (_, viewport) => {
    setViewport(viewport);
    renderStored();
    expect(screen.getByRole("button", { name: "Fäll ut sidomenyn" })).toBeTruthy();
    // A rail item keeps its name: the space's name, not its initial.
    expect(screen.getByRole("link", { name: "Upphandling" })).toBeTruthy();
  });

  it("is the full nav from 1280 px when nothing is stored", () => {
    setViewport({ width: 1280, height: 800, pointer: "fine" });
    renderStored();
    expect(expanded()).toBe(true);
  });

  it("follows the width until the user chooses, then keeps the choice", () => {
    setViewport("tablet-landscape");
    renderStored();
    expect(expanded()).toBe(false);
    act(() => setViewport("desktop"));
    expect(expanded()).toBe(true);
    act(() => setViewport("tablet-landscape"));
    expect(expanded()).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Fäll ut sidomenyn" }));
    expect(document.cookie).toContain(`${SIDE_NAV_COLLAPSED_COOKIE}=0`);
    act(() => setViewport("tablet-portrait"));
    expect(expanded()).toBe(true);
  });

  it("keeps focus in the rail when narrowing below 1280 px removes the focused control", async () => {
    setViewport({ width: 1280, height: 800, pointer: "fine" });
    setRoute("/spaces/s1/overview");
    const queryClient = seededClient();
    queryClient.setQueryData(
      spaceQueryOptions(browserApi, "s1").queryKey,
      makeSpace({ overrides: { id: "s1", name: "Upphandling" } })
    );
    renderInApp(<SpaceSideNav />, { queryClient, appContext: testAppContext() });
    // The space switcher's trigger is another element in the icon rail.
    const trigger = screen.getByRole("button", { name: "Upphandling, Öppna meny" });
    trigger.focus();

    act(() => setViewport({ width: 1279, height: 800, pointer: "fine" }));

    // Astryx moves it to the nearest row the rail keeps: the current page.
    await waitFor(() => expect(document.activeElement?.getAttribute("aria-current")).toBe("page"));
    expect(
      screen.getByRole("navigation", { name: "Ytans meny" }).contains(document.activeElement)
    ).toBe(true);
  });

  it("leaves focus outside the nav where it was when the width collapses the nav", async () => {
    setViewport({ width: 1280, height: 800, pointer: "fine" });
    renderStored();
    const outside = document.createElement("button");
    document.body.append(outside);
    outside.focus();

    act(() => setViewport({ width: 1279, height: 800, pointer: "fine" }));

    expect(screen.getByRole("button", { name: "Fäll ut sidomenyn" })).toBeTruthy();
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(document.activeElement).toBe(outside);
    outside.remove();
  });

  it.each([
    ["expanded", false],
    ["collapsed", true]
  ])("keeps a stored %s nav from 1024 px", (_, collapsed) => {
    setViewport({ width: 1024, height: 768, pointer: "fine" });
    renderStored(collapsed);
    expect(expanded()).toBe(!collapsed);
    act(() => setViewport("desktop"));
    expect(expanded()).toBe(!collapsed);
  });

  it("is the icon rail below 1024 px whatever was stored, until the toggle is pressed", () => {
    setViewport({ width: 1023, height: 768, pointer: "fine" });
    renderStored(false);
    expect(expanded()).toBe(false);
    act(() => setViewport("desktop"));
    expect(expanded()).toBe(true);
    act(() => setViewport("tablet-portrait"));
    expect(expanded()).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Fäll ut sidomenyn" }));
    expect(expanded()).toBe(true);
    expect(document.cookie).toContain(`${SIDE_NAV_COLLAPSED_COOKIE}=0`);
  });
});

describe("DesktopSideNav (admin)", () => {
  it("lists every admin section under the Administration landmark", async () => {
    setRoute("/admin/models");
    const { container } = renderNav({ variant: "admin", permissions: ["admin"] });
    const navigation = screen.getByRole("navigation", { name: "Administration" });

    // Four groups in this order, each with its pages in the design's order.
    const groupNames = ["Uppföljning", "Styrning", "Anslutningar", "Organisation"];
    const groups = groupNames.map((name) => within(navigation).getByRole("group", { name }));
    for (const [index, group] of groups.entries()) {
      const next = groups[index + 1];
      if (next)
        expect(group.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    // "Tillbaka till Eneo" comes first, before any admin page.
    const back = within(navigation).getByRole("link", { name: "Tillbaka till Eneo" });
    expect(
      back.compareDocumentPosition(groups[0]!) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    const links = within(navigation).getAllByRole("link");
    // No group shares its name with a page: a screen reader would hear the same word twice in a row.
    const linkNames = links.map((link) => link.textContent);
    expect(groupNames.filter((name) => linkNames.includes(name))).toEqual([]);
    const hrefsIn = (name: string) =>
      within(within(navigation).getByRole("group", { name }))
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"));
    expect(hrefsIn("Uppföljning")).toEqual(["/admin", "/admin/insights", "/admin/usage"]);
    expect(hrefsIn("Styrning")).toEqual([
      "/admin/personal-assistant",
      "/admin/prompt-library",
      "/admin/skills",
      "/admin/security-classifications",
      "/admin/widgets",
      "/admin/audit-logs"
    ]);
    expect(hrefsIn("Anslutningar")).toEqual([
      "/admin/models",
      "/admin/integrations",
      "/admin/federation",
      "/admin/tools",
      "/admin/api-keys"
    ]);
    expect(hrefsIn("Organisation")).toEqual([
      "/admin/users",
      "/admin/user-groups",
      "/admin/roles",
      "/admin/help-assistants",
      "/admin/storage",
      "/admin/crawler",
      "/admin/settings"
    ]);
    expect(within(navigation).getByRole("link", { name: "Översikt" }).getAttribute("href")).toBe(
      "/admin"
    );
    expect(within(navigation).getByRole("link", { name: "Inställningar" })).toBeTruthy();

    // Gated: templates (tenant setting) and modules (permission).
    const hrefs = links.map((link) => link.getAttribute("href"));
    expect(hrefs).not.toContain("/admin/templates");
    expect(hrefs).not.toContain("/admin/modules");
    expect(screen.getByRole("link", { name: "Modeller" }).getAttribute("aria-current")).toBe(
      "page"
    );
    await expectNoAxeViolations(container);
  });

  it("keeps the gated pages in their groups and no group above seven items", () => {
    setRoute("/admin");
    renderInApp(<RailedSideNav variant="admin" navId="side-nav" />, {
      queryClient: seededClient(),
      appContext: testAppContext({
        permissions: ["admin", "modules"],
        settings: { using_templates: true }
      })
    });
    const navigation = screen.getByRole("navigation", { name: "Administration" });
    const connections = within(navigation).getByRole("group", { name: "Anslutningar" });
    const governance = within(navigation).getByRole("group", { name: "Styrning" });
    expect(within(connections).getByRole("link", { name: "Moduler" })).toBeTruthy();
    expect(within(governance).getByRole("link", { name: "Mallar" })).toBeTruthy();
    for (const name of ["Uppföljning", "Styrning", "Anslutningar", "Organisation"]) {
      const group = within(navigation).getByRole("group", { name });
      expect(within(group).getAllByRole("link").length).toBeLessThanOrEqual(7);
    }
    // Only the landing is current on /admin.
    expect(currentLinks()).toEqual([within(navigation).getByRole("link", { name: "Översikt" })]);
  });

  it("lists the flow settings under Styrning only when the tenant has flows", () => {
    setRoute("/admin/flow-settings");
    renderInApp(<RailedSideNav variant="admin" navId="side-nav" />, {
      queryClient: seededClient(),
      // The tenant's switch decides: this admin may not see flows themselves.
      appContext: testAppContext({
        permissions: ["admin"],
        settings: { flows_enabled: true },
        featureFlags: { flows: false }
      })
    });
    const governance = within(screen.getByRole("navigation", { name: "Administration" })).getByRole(
      "group",
      { name: "Styrning" }
    );
    const flows = within(governance).getByRole("link", { name: "Flöden" });
    expect(flows.getAttribute("href")).toBe("/admin/flow-settings");
    expect(flows.getAttribute("aria-current")).toBe("page");
    expect(
      within(governance)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"))
    ).toEqual([
      "/admin/personal-assistant",
      "/admin/prompt-library",
      "/admin/skills",
      "/admin/flow-settings",
      "/admin/flow-data-retention",
      "/admin/security-classifications",
      "/admin/widgets",
      "/admin/audit-logs"
    ]);
    cleanup();

    renderNav({ variant: "admin", permissions: ["admin"] });
    expect(screen.queryByRole("link", { name: "Flöden" })).toBeNull();
  });
});

describe("help centre link", () => {
  const HELP_CENTER = "https://support.example.se/eneo";

  function renderWithHelpCenter(variant: NavVariant, helpCenter: string | null) {
    return renderInApp(<RailedSideNav variant={variant} navId="side-nav" />, {
      queryClient: seededClient(),
      appContext: testAppContext({ permissions: ["admin"], links: { helpCenter } })
    });
  }

  it.each(["main", "admin"] as const)(
    "opens the deployment's help centre in a new tab from the %s navigation, and says so",
    async (variant) => {
      setRoute(variant === "admin" ? "/admin" : "/spaces/personal/chat");
      const { container } = renderWithHelpCenter(variant, HELP_CENTER);
      const link = screen.getByRole("link", { name: "Har du en fråga? (öppnas i en ny flik)" });

      expect(link.getAttribute("href")).toBe(HELP_CENTER);
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")?.split(" ")).toEqual(
        expect.arrayContaining(["noopener", "noreferrer"])
      );
      // The visible text is in the name (WCAG 2.5.3), and it is never the current page.
      expect(link.textContent).toContain("Har du en fråga?");
      expect(link.getAttribute("aria-current")).toBeNull();
      await expectNoAxeViolations(container);
    }
  );

  it("keeps the name in the icon rail", async () => {
    document.cookie = `${SIDE_NAV_COLLAPSED_COOKIE}=1; path=/`;
    renderInApp(<RailedSideNav variant="main" navId="side-nav" defaultCollapsed />, {
      queryClient: seededClient(),
      appContext: testAppContext({ links: { helpCenter: HELP_CENTER } })
    });
    expect(
      screen
        .getByRole("link", { name: "Har du en fråga? (öppnas i en ny flik)" })
        .getAttribute("href")
    ).toBe(HELP_CENTER);
  });

  it("is absent when the deployment has no help centre", () => {
    renderWithHelpCenter("main", null);
    expect(screen.queryByRole("link", { name: /Har du en fråga/ })).toBeNull();
  });
});
