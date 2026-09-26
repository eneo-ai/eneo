// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
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
import { recentConversationsQueryOptions } from "./nav-data";
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

function seededClient({ conversations = true } = {}) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces"], SPACES);
  queryClient.setQueryData(["spaces", "personal"], {
    id: "p",
    personal: true,
    default_assistant: { id: "default-assistant" }
  });
  queryClient.setQueryData(
    recentConversationsQueryOptions(browserApi, "default-assistant", 5).queryKey,
    conversations
      ? [
          { id: "c1", name: "Upphandlingsanalys mot LOU" },
          { id: "c2", name: "Sammanfatta KS-protokoll" }
        ]
      : []
  );
  return queryClient;
}

function renderNav({
  variant = "main" as NavVariant,
  permissions = [] as Permission[],
  conversations = true,
  shell = { ...noopShell, openPalette: vi.fn(), openCreateSpace: vi.fn() }
} = {}) {
  const utils = renderInApp(<DesktopSideNav variant={variant} navId="side-nav" />, {
    queryClient: seededClient({ conversations }),
    appContext: testAppContext({ permissions }),
    shell
  });
  return { ...utils, shell };
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

    const recent = within(navigation).getByRole("group", { name: "Senaste" });
    expect(
      within(recent)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"))
    ).toEqual(["/spaces/personal/chat?session_id=c1", "/spaces/personal/chat?session_id=c2"]);

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

    setRoute("/spaces/personal/chat?session_id=c2");
    renderNav();
    expect(
      screen.getByRole("link", { name: "Sammanfatta KS-protokoll" }).getAttribute("aria-current")
    ).toBe("page");
    expect(
      screen.getByRole("link", { name: "Ny konversation" }).getAttribute("aria-current")
    ).toBeNull();
    cleanup();

    setRoute("/spaces/s2/knowledge");
    renderNav();
    const current = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("aria-current") === "page");
    expect(current).toEqual([screen.getByRole("link", { name: "Socialtjänst" })]);
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
    renderNav({ conversations: false });
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
