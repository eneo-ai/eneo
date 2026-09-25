// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { recentConversationsQueryOptions } from "./nav-data";
import { resetSideNavCollapsedForTest, SIDE_NAV_COLLAPSED_KEY } from "./shell-state";
import type { NavVariant } from "./routes";
import { DesktopSideNav } from "./side-nav";
import {
  appContext,
  installBrowserMocks,
  renderWithProviders,
  testQueryClient
} from "./test-support";

const nav = vi.hoisted(() => ({ pathname: "/spaces/personal/chat", search: "" }));

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
  shell = { openPalette: vi.fn(), openCreateSpace: vi.fn() }
} = {}) {
  const utils = renderWithProviders(<DesktopSideNav variant={variant} navId="side-nav" />, {
    queryClient: seededClient({ conversations }),
    context: appContext({ permissions }),
    shell
  });
  return { ...utils, shell };
}

beforeEach(() => {
  installBrowserMocks();
  nav.pathname = "/spaces/personal/chat";
  nav.search = "";
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  resetSideNavCollapsedForTest();
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
    nav.pathname = "/spaces/personal/chat";
    renderNav();
    expect(screen.getByRole("link", { name: "Ny konversation" }).getAttribute("aria-current")).toBe(
      "page"
    );
    cleanup();

    nav.search = "session_id=c2";
    renderNav();
    expect(
      screen.getByRole("link", { name: "Sammanfatta KS-protokoll" }).getAttribute("aria-current")
    ).toBe("page");
    expect(
      screen.getByRole("link", { name: "Ny konversation" }).getAttribute("aria-current")
    ).toBeNull();
    cleanup();

    nav.pathname = "/spaces/s2/knowledge";
    nav.search = "";
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
    expect(window.localStorage.getItem(SIDE_NAV_COLLAPSED_KEY)).toBe("1");
    // Icon rail: titles-only rows (Senaste) and the section actions are gone,
    // icon rows keep their names.
    expect(screen.queryByRole("group", { name: "Senaste" })).toBeNull();
    expect(screen.getByRole("link", { name: "Upphandling" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });
});

describe("DesktopSideNav (admin)", () => {
  it("lists every admin section under the Administration landmark", async () => {
    nav.pathname = "/admin/models";
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
