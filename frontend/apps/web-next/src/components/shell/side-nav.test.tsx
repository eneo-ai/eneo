// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { recentConversationsQueryOptions, type RecentConversation } from "@/lib/api/conversations";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { setRoute } from "@/test/navigation";
import {
  noopShell,
  renderInApp,
  renderToHtml,
  testAppContext,
  testQueryClient
} from "@/test/render";
import type { NavVariant } from "./routes";
import { DesktopSideNav } from "./side-nav";
import { SIDE_NAV_COLLAPSED_COOKIE } from "./side-nav-preference";

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/jobs/job-indicator", () => ({ JobIndicator: () => null }));
vi.mock("@/features/api-keys/expiring-keys-notification", () => ({
  ExpiringKeysNotification: () => null
}));
vi.mock("@/features/whats-new/whats-new-provider", () => ({
  useWhatsNew: () => ({ enabled: false, hasUnseen: false })
}));
vi.mock("@/lib/i18n/actions", () => ({ setLocale: vi.fn() }));

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
  const utils = renderInApp(<DesktopSideNav variant={variant} navId="side-nav" />, {
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
});

describe("DesktopSideNav (main)", () => {
  it("is a named navigation landmark with the design's destinations", async () => {
    const { container } = renderNav();
    const navigation = screen.getByRole("navigation", { name: "Huvudmeny" });

    expect(
      within(navigation).getByRole("link", { name: "Ny konversation" }).getAttribute("href")
    ).toBe("/spaces/personal/chat");
    expect(within(navigation).getByRole("button", { name: "Sök" })).toBeTruthy();
    expect(within(navigation).getByRole("link", { name: "Assistenter" }).getAttribute("href")).toBe(
      "/dashboard"
    );

    // Personligt first, the shared spaces (not the organisation space), Alla ytor last.
    const spaces = within(navigation).getByRole("group", { name: "Ytor" });
    const spaceLinks = within(spaces).getAllByRole("link");
    expect(spaceLinks.map((link) => link.getAttribute("href"))).toEqual([
      "/spaces/personal/overview",
      "/spaces/s1/overview",
      "/spaces/s2/overview",
      "/spaces/list"
    ]);
    for (const name of ["Personligt", "Upphandling", "Socialtjänst", "Alla ytor"]) {
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

  it("shows Organisation and Administration to admins only", () => {
    renderNav();
    expect(screen.queryByRole("link", { name: "Administration" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Organisation" })).toBeNull();
    cleanup();

    renderNav({ permissions: ["admin"] });
    expect(screen.getByRole("link", { name: "Administration" }).getAttribute("href")).toBe(
      "/admin"
    );
    expect(screen.getByRole("link", { name: "Organisation" }).getAttribute("href")).toBe(
      "/spaces/organization/knowledge"
    );
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

  it("opens the command palette from Sök and advertises the shortcut", () => {
    const { shell } = renderNav();
    const search = screen.getByRole("button", { name: "Sök" });
    expect(search.getAttribute("aria-keyshortcuts")).toBe("Meta+K Control+K");
    fireEvent.click(search);
    expect(shell.openPalette).toHaveBeenCalledTimes(1);
  });

  it("hides Senaste when there are no conversations", () => {
    renderNav({ conversations: [] });
    expect(screen.queryByRole("group", { name: "Senaste" })).toBeNull();
  });

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

  it("renders the stored preference on the server, so the nav does not jump", () => {
    // What the server layout sends when the cookie says "collapsed".
    const html = renderToHtml(<DesktopSideNav variant="main" navId="side-nav" defaultCollapsed />, {
      queryClient: seededClient()
    });
    expect(html).toContain('aria-label="Fäll ut sidomenyn"');
    expect(html).not.toContain("Fäll ihop sidomenyn");
  });
});

describe("DesktopSideNav (admin)", () => {
  it("lists every admin section under the Administration landmark", async () => {
    setRoute("/admin/models");
    const { container } = renderNav({ variant: "admin", permissions: ["admin"] });
    const navigation = screen.getByRole("navigation", { name: "Administration" });

    expect(within(navigation).getByRole("link", { name: "Tillbaka till Eneo" })).toBeTruthy();
    for (const name of ["Översikt", "Styrning", "Konfiguration", "Användare och åtkomst"]) {
      expect(within(navigation).getByRole("group", { name })).toBeTruthy();
    }

    const hrefs = within(navigation)
      .getAllByRole("link")
      .map((link) => link.getAttribute("href"));
    for (const href of [
      "/admin",
      "/admin/insights",
      "/admin/usage",
      "/admin/personal-assistant",
      "/admin/prompt-library",
      "/admin/security-classifications",
      "/admin/audit-logs",
      "/admin/models",
      "/admin/help-assistants",
      "/admin/mcp-servers",
      "/admin/tools",
      "/admin/integrations",
      "/admin/storage",
      "/admin/skills",
      "/admin/users",
      "/admin/roles",
      "/admin/api-keys"
    ]) {
      expect(hrefs).toContain(href);
    }
    // Gated: templates (tenant setting) and modules (permission).
    expect(hrefs).not.toContain("/admin/templates");
    expect(hrefs).not.toContain("/admin/modules");
    expect(screen.getByRole("link", { name: "Modeller" }).getAttribute("aria-current")).toBe(
      "page"
    );
    await expectNoAxeViolations(container);
  });
});
