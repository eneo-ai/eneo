import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { AdminSpaceList, AdminSpaceListItem } from "@eneo/eneo-js";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import sv from "../../../../../messages/sv.json";
import "../../../../app.css";

const navigation = vi.hoisted(() => ({ invalidate: vi.fn(), replaceState: vi.fn() }));
const route = vi.hoisted(() => ({ url: new URL("http://localhost/admin/spaces") }));
// Messages read as their keys, or as the real Swedish text where length matters.
const i18n = vi.hoisted(() => ({ catalog: null as Record<string, string> | null }));

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: navigation.invalidate,
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: navigation.replaceState
}));
vi.mock("$app/state", () => ({
  page: {
    get url() {
      return route.url;
    },
    state: {}
  },
  navigating: { to: null }
}));
vi.mock("$lib/core/AppContext", () => ({ getAppContext: () => ({ user: { id: "me" } }) }));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({ icons: { url: () => "" } }) }));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) => {
        const text = i18n.catalog?.[String(key)];
        if (text) return text.replace(/\{(\w+)\}/g, (_, name) => String(params?.[name] ?? ""));
        return params ? `${String(key)}(${Object.values(params).join("|")})` : String(key);
      }
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));

import SpacesPage from "./+page.svelte";

function space(name: string, patch: Partial<AdminSpaceListItem> = {}): AdminSpaceListItem {
  return {
    id: `id-${name.toLowerCase().replace(/\W+/g, "-")}`,
    name,
    description: `Allt om ${name.toLowerCase()} för medarbetarna i förvaltningen`,
    created_at: "2026-01-01T00:00:00Z",
    security_classification: { id: "sc", name: "Intern", security_level: 1 },
    member_count: 12,
    group_count: 2,
    admins: {
      manageable: true,
      count: 2,
      principals: [
        { kind: "user", id: "u1", name: "Ada Lind" },
        { kind: "user", id: "u2", name: "Bo Ek" },
        { kind: "group", id: "g1", name: "Förvaltningsledning" }
      ]
    },
    resources: { assistants: 3, apps: 1, group_chats: 0, knowledge_sources: 4 },
    widgets: { active: 1, paused: 0, draft: 0, awaiting_activation: 0 },
    last_activity: "past_week",
    viewer_membership: { role: null, via_group_only: false },
    attention: [],
    ...patch
  };
}

const ekonomi = space("Ekonomi", {
  viewer_membership: { role: "viewer", via_group_only: false },
  member_count: 40,
  last_activity: "older"
});
const hr = space("HR", {
  attention: ["no_admin"],
  admins: { manageable: false, count: 0, principals: [] },
  member_count: 3,
  last_activity: "none"
});
const webb = space("Webb och kommunikation", {
  attention: ["widget_activation_requested"],
  viewer_membership: { role: "admin", via_group_only: false, oversight_joined_at: "2026-09-01" },
  member_count: 8
});

const requests: AdminSpaceList["widget_requests"] = [
  {
    widget_id: "w1",
    widget_name: "Fråga kommunen",
    space: { id: webb.id, name: webb.name },
    requested_at: "2026-09-20T10:00:00Z",
    requested_by: { id: "u9", name: "Eva", email: "eva@example.org" }
  }
];

let shell: HTMLDivElement;

function renderPage(
  list: AdminSpaceList | null = { items: [ekonomi, hr, webb], widget_requests: requests },
  securityEnabled = true
) {
  // The app shell gives the page its height; without it the scrolling main area has none.
  shell = document.createElement("div");
  shell.className = "flex h-screen flex-col";
  document.body.append(shell);
  return render(SpacesPage, { target: shell, props: { data: { list, securityEnabled } as never } });
}

const status = () => page.getByRole("status");
const heading = () => page.getByRole("heading", { level: 2, name: "admin_spaces_all_title" });
const rows = () =>
  page
    .getByRole("rowheader")
    .elements()
    .map((cell) => cell.querySelector("a")?.textContent?.trim());

async function settled() {
  await userEvent.unhover(document.body);
  await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
}

async function axeViolations() {
  await settled();
  const result = await axe.run(document, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
    },
    rules: { "landmark-one-main": { enabled: false }, region: { enabled: false } }
  });
  return result.violations.flatMap((violation) =>
    violation.nodes.map((node) => `${violation.id}: ${node.html}`)
  );
}

/** Elements that scroll sideways or stick out of the page at the current width. */
function horizontalOverflow() {
  const width = document.documentElement.clientWidth;
  const elements = [...shell.querySelectorAll<HTMLElement>("*")].filter(
    (element) => !element.closest(".sr-only") && element.getClientRects().length > 0
  );
  return [
    ...elements
      .filter(
        (element) =>
          ["auto", "scroll"].includes(getComputedStyle(element).overflowX) &&
          element.scrollWidth > element.clientWidth + 1
      )
      .map((element) => `scrolls: ${element.outerHTML.slice(0, 80)}`),
    ...elements
      .filter((element) => element.getBoundingClientRect().right > width + 1)
      .map((element) => `outside: ${element.outerHTML.slice(0, 80)}`)
  ];
}

beforeEach(() => {
  vi.clearAllMocks();
  navigation.invalidate.mockResolvedValue(undefined);
  route.url = new URL("http://localhost/admin/spaces");
  i18n.catalog = null;
  delete document.documentElement.dataset.theme;
  document.body.classList.add("bg-primary");
});

afterEach(async () => {
  document.body.classList.remove("bg-primary");
  await page.viewport(1280, 720);
});

describe("Admin → Ytor", () => {
  test("lists what needs attention: spaces without an administrator and widget requests", async () => {
    renderPage();

    const attention = page.getByRole("region", { name: "admin_spaces_attention_title" });
    await expect.element(attention).toHaveTextContent("admin_spaces_attention_no_admin_one");
    await expect.element(attention).toHaveTextContent("admin_spaces_attention_widgets_one");
    const review = page.getByRole("link", { name: "admin_spaces_review_named(Fråga kommunen)" });
    await expect.element(review).toHaveAttribute("href", "/admin/widgets/w1");
    await expect.element(review).toHaveTextContent("admin_spaces_review");
    expect(attention.element().textContent).not.toContain("admin_spaces_attention_none");
  });

  test("says calmly when nothing needs attention", async () => {
    renderPage({ items: [ekonomi], widget_requests: [] });

    const attention = page.getByRole("region", { name: "admin_spaces_attention_title" });
    await expect.element(attention).toHaveTextContent("admin_spaces_attention_none");
    expect(attention.element().querySelectorAll("button, a")).toHaveLength(0);
  });

  test("links to the widget overview when more requests wait than it shows", async () => {
    const many = Array.from({ length: 5 }, (_, index) => ({
      ...requests[0],
      widget_id: `w${index}`,
      widget_name: `Widget ${index}`
    }));
    renderPage({ items: [webb], widget_requests: many });

    await expect.element(page.getByText("admin_spaces_attention_widgets(5)")).toBeVisible();
    expect(page.getByRole("link", { name: /^admin_spaces_review_named/ }).elements()).toHaveLength(
      3
    );
    await expect
      .element(page.getByRole("link", { name: "admin_spaces_attention_all_widgets" }))
      .toHaveAttribute("href", "/admin/widgets?tab=widgets#activation-requests");
  });

  test("'Visa ytorna' narrows the list, moves focus to it and announces the new count", async () => {
    renderPage();
    await expect.element(status()).toHaveTextContent("admin_spaces_results(3|3)");

    await page.getByRole("button", { name: "admin_spaces_attention_show" }).click();

    await expect.element(heading()).toHaveFocus();
    expect(rows()).toEqual(["HR"]);
    await expect
      .element(page.getByRole("button", { name: /^show admin_spaces_show_no_admin$/ }))
      .toBeVisible();
    await expect.element(status()).toHaveTextContent("admin_spaces_results(1|3)");
    await vi.waitFor(() =>
      expect(navigation.replaceState).toHaveBeenLastCalledWith("/admin/spaces?show=no_admin", {})
    );
  });

  test("search, membership and 'Visa' filter at once; the count is announced once typing pauses", async () => {
    renderPage();

    await page.getByRole("searchbox", { name: "admin_spaces_search_label" }).fill("webb");
    expect(rows()).toEqual(["Webb och kommunikation"]);
    // Still the old count right after the keystrokes; the new one follows the pause.
    expect(status().element().textContent).toBe("admin_spaces_results(3|3)");
    await expect.element(status()).toHaveTextContent("admin_spaces_results(1|3)");

    await page.getByRole("searchbox", { name: "admin_spaces_search_label" }).fill("");
    await page.getByRole("radio", { name: "admin_spaces_membership_not_member(1)" }).click();
    expect(rows()).toEqual(["HR"]);
    await expect
      .element(page.getByRole("radio", { name: "admin_spaces_membership_member(2)" }))
      .toHaveAttribute("aria-checked", "false");
    await expect.element(status()).toHaveTextContent("admin_spaces_results(1|3)");

    await page.getByRole("radio", { name: "admin_spaces_membership_all(3)" }).click();
    await page.getByRole("button", { name: /^show admin_spaces_show_all$/ }).click();
    await page.getByRole("option", { name: "admin_spaces_show_widget_request" }).click();
    expect(rows()).toEqual(["Webb och kommunikation"]);
    await expect.element(status()).toHaveTextContent("admin_spaces_results(1|3)");
    await vi.waitFor(() =>
      expect(navigation.replaceState).toHaveBeenLastCalledWith(
        "/admin/spaces?show=widget_request",
        {}
      )
    );
  });

  test("the membership options sit in a named group with a visible legend", async () => {
    renderPage();
    const group = page.getByRole("group", { name: "admin_spaces_membership_legend" });
    await expect.element(group).toBeVisible();
    await expect
      .element(page.getByRole("radiogroup", { name: "admin_spaces_membership_legend" }))
      .toBeVisible();
    await expect
      .element(page.getByRole("search", { name: "admin_spaces_filters_label" }))
      .toBeVisible();
  });

  test("sorting marks only the sorted column and says so in the caption", async () => {
    renderPage();
    const nameHeader = () =>
      page.getByRole("columnheader", { name: /admin_spaces_sort_by\(admin_spaces_col_space\)/ });
    const membersHeader = () =>
      page.getByRole("columnheader", { name: /admin_spaces_sort_by\(members\)/ });

    await expect.element(nameHeader()).toHaveAttribute("aria-sort", "ascending");
    expect(membersHeader().element().hasAttribute("aria-sort")).toBe(false);
    expect(document.querySelector("caption")?.textContent).toBe(
      "admin_spaces_table_caption(admin_spaces_col_space)"
    );

    await page
      .getByRole("button", { name: "admin_spaces_sort_by(admin_spaces_col_space)" })
      .click();
    await expect.element(nameHeader()).toHaveAttribute("aria-sort", "descending");
    expect(rows()).toEqual(["Webb och kommunikation", "HR", "Ekonomi"]);

    await page.getByRole("button", { name: "admin_spaces_sort_by(members)" }).click();
    await expect.element(membersHeader()).toHaveAttribute("aria-sort", "descending");
    expect(nameHeader().element().hasAttribute("aria-sort")).toBe(false);
    expect(rows()).toEqual(["Ekonomi", "Webb och kommunikation", "HR"]);
    expect(document.querySelector("caption")?.textContent).toBe(
      "admin_spaces_table_caption(members)"
    );
  });

  test("links each space by name and gives every 'Öppna ytan' a unique name", async () => {
    await page.viewport(1440, 900);
    renderPage();

    await expect
      .element(page.getByRole("link", { name: "Ekonomi", exact: true }))
      .toHaveAttribute("href", `/admin/spaces/${ekonomi.id}`);
    const open = page.getByRole("link", { name: /^admin_spaces_open_space_named/ }).elements();
    expect(open.map((link) => link.getAttribute("aria-label"))).toEqual([
      "admin_spaces_open_space_named(Ekonomi)",
      "admin_spaces_open_space_named(Webb och kommunikation)"
    ]);
    expect(open.map((link) => link.textContent?.trim())).toEqual([
      "admin_spaces_open_space",
      "admin_spaces_open_space"
    ]);
    expect(open[1].getAttribute("href")).toBe(`/spaces/${webb.id}/overview`);
    // Not a member of HR: nothing to open.
    const hrRow = page.getByRole("row", { name: /^HR/ });
    await expect.element(hrRow).toHaveTextContent("admin_spaces_not_member");
    await expect.element(hrRow).toHaveTextContent("admin_spaces_admins_missing");
  });

  test("says when the organisation has no shared spaces, without filters or table", async () => {
    renderPage({ items: [], widget_requests: [] });

    await expect.element(page.getByText("admin_spaces_empty_tenant")).toBeVisible();
    expect(page.getByRole("search").elements()).toHaveLength(0);
    expect(page.getByRole("table").elements()).toHaveLength(0);
  });

  test("an empty result offers to clear the filters and returns focus to the search", async () => {
    renderPage();
    const search = page.getByRole("searchbox", { name: "admin_spaces_search_label" });

    await search.fill("finns inte");
    await expect
      .element(page.getByRole("cell", { name: /admin_spaces_empty_filtered/ }))
      .toBeVisible();
    await page.getByRole("button", { name: "admin_spaces_clear_filters" }).last().click();

    await expect.element(search).toHaveValue("");
    await expect.element(search).toHaveFocus();
    expect(rows()).toHaveLength(3);
  });

  test("pages through 50 spaces at a time and moves focus to the list", async () => {
    const items = Array.from({ length: 55 }, (_, index) =>
      space(`Yta ${String(index + 1).padStart(2, "0")}`)
    );
    renderPage({ items, widget_requests: [] });

    const pagination = page.getByRole("navigation", { name: "admin_spaces_pagination_label" });
    await expect.element(pagination).toHaveTextContent("admin_spaces_page_of(1|2)");
    expect(rows()).toHaveLength(50);

    await page.getByRole("button", { name: "next" }).click();
    await expect.element(pagination).toHaveTextContent("admin_spaces_page_of(2|2)");
    expect(rows()).toEqual(["Yta 51", "Yta 52", "Yta 53", "Yta 54", "Yta 55"]);
    await expect.element(heading()).toHaveFocus();
    await expect.element(page.getByRole("button", { name: "next" })).toBeDisabled();
    // The page is not a live region; the status keeps the total.
    expect(pagination.element().closest("[aria-live], [role=status]")).toBeNull();
  });

  test("reads the list's state from the URL", async () => {
    route.url = new URL("http://localhost/admin/spaces?q=ekonomi&sort=members");
    renderPage();

    await expect.element(page.getByRole("searchbox")).toHaveValue("ekonomi");
    expect(rows()).toEqual(["Ekonomi"]);
    await expect
      .element(page.getByRole("columnheader", { name: /admin_spaces_sort_by\(members\)/ }))
      .toHaveAttribute("aria-sort", "descending");
  });

  test("offers another try when the spaces could not be loaded", async () => {
    renderPage(null);

    await expect.element(page.getByRole("alert")).toHaveTextContent("admin_spaces_load_failed");
    await page.getByRole("button", { name: "retry" }).click();
    expect(navigation.invalidate).toHaveBeenCalledWith("admin:spaces");
  });

  test("leaves out the classification when the organisation does not use it", async () => {
    await page.viewport(1440, 900);
    renderPage(undefined, false);
    await expect.element(page.getByRole("table")).toBeVisible();
    expect(
      page.getByRole("columnheader", { name: "admin_spaces_col_classification" }).elements()
    ).toHaveLength(0);
    expect(document.body.textContent).not.toContain("Intern");
  });

  test.each([
    [320, 720],
    [768, 900],
    [1440, 900]
  ])("reflows at %i px without scrolling sideways, in Swedish", async (width, height) => {
    i18n.catalog = sv;
    await page.viewport(width, height);
    // One long Swedish compound is wider than a phone's name column on its own.
    const long = space("Barn- och utbildningsförvaltningen", {
      admins: {
        manageable: true,
        count: 1,
        principals: [{ kind: "group", id: "g", name: "Förskoleverksamhetsutvecklingsgruppen" }]
      }
    });
    renderPage({ items: [ekonomi, hr, webb, long], widget_requests: requests });
    await expect.element(page.getByRole("table")).toBeVisible();

    expect(horizontalOverflow()).toEqual([]);
    // What the hidden columns hold stays on the page.
    const hrRow = page.getByRole("row", { name: /^HR/ });
    await expect.element(hrRow).toHaveTextContent("Saknas");
    await expect.element(hrRow).toHaveTextContent("Ingen aktivitet");
  });

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      await page.viewport(1440, 900);
      renderPage();
      await expect.element(page.getByRole("table")).toBeVisible();
      expect(await axeViolations()).toEqual([]);

      await page.viewport(320, 720);
      expect(await axeViolations()).toEqual([]);
    }
  );
});
