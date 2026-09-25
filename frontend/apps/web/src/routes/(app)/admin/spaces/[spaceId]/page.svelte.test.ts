import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type {
  AdminSpaceAssistant,
  AdminSpaceDetail,
  AdminSpaceViewerMembership
} from "@eneo/eneo-js";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import sv from "../../../../../../messages/sv.json";
import "../../../../../app.css";

const navigation = vi.hoisted(() => ({
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  replaceState: vi.fn()
}));
const route = vi.hoisted(() => ({
  url: new URL("http://localhost/admin/spaces/space-1"),
  state: {} as App.PageState
}));
const admin = vi.hoisted(() => ({ leave: vi.fn(), join: vi.fn() }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
// Messages read as their keys, or as the real Swedish text where length matters.
const i18n = vi.hoisted(() => ({ catalog: null as Record<string, string> | null }));

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: navigation.invalidate,
  invalidateAll: navigation.invalidateAll,
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
    get state() {
      return route.state;
    }
  }
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    spaces: { admin },
    users: { list: async () => ({ items: [], total_count: 0 }) },
    userGroups: { list: async () => [] }
  })
}));
vi.mock("$lib/components/toast", () => ({ toast }));
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

import SpacePage from "./+page.svelte";

const viewing: AdminSpaceViewerMembership = {
  role: null,
  direct_role: null,
  group_role: null,
  via_groups: [],
  oversight_joined_at: null,
  joinable_roles: ["viewer", "editor", "admin"],
  can_leave: false
};
const joined: AdminSpaceViewerMembership = {
  ...viewing,
  role: "viewer",
  direct_role: "viewer",
  oversight_joined_at: "2026-09-20T09:00:00Z",
  joinable_roles: [],
  can_leave: true
};
const viaGroup: AdminSpaceViewerMembership = {
  ...viewing,
  role: "editor",
  group_role: "editor",
  via_groups: [{ id: "g-stod", name: "Ekonomistöd" }],
  joinable_roles: ["admin"]
};

function assistant(name: string, patch: Partial<AdminSpaceAssistant> = {}): AdminSpaceAssistant {
  return {
    id: `a-${name}`,
    name,
    description: "Svarar på frågor om budgetprocessen och förvaltningarnas prognoser.",
    published: true,
    is_default: false,
    updated_at: "2026-09-01T10:00:00Z",
    completion_model: { id: "m1", name: "GPT-5", hosting: "eu", org: "OpenAI" },
    instructions: "Du är en hjälpsam assistent för ekonomiavdelningen.\nSvara kort och sakligt.",
    knowledge_mode: "tool",
    knowledge: [
      { id: "k1", name: "Budgethandboken", kind: "collection", from_organization: false },
      { id: "k9", name: "Kommungemensamma riktlinjer", kind: "collection", from_organization: true }
    ],
    attachment_count: 2,
    mcp_servers: [{ id: "mcp1", name: "Diariet" }],
    capabilities: ["web_search"],
    insight_enabled: true,
    logging_enabled: false,
    data_retention_days: null,
    widgets: [],
    ...patch
  };
}

function detail(patch: Partial<AdminSpaceDetail> = {}): AdminSpaceDetail {
  return {
    id: "space-1",
    name: "Ekonomi",
    description: "Budget, prognoser och uppföljning för förvaltningarna.",
    icon_id: null,
    created_at: "2025-03-14T09:00:00Z",
    updated_at: "2026-09-01T09:00:00Z",
    security_classification: { id: "sc", name: "Konfidentiell", security_level: 3 },
    settings: {
      completion_models: [{ id: "m1", name: "GPT-5", hosting: "eu", org: "OpenAI" }],
      embedding_models: [{ id: "e1", name: "text-embedding-3", hosting: "eu", org: "OpenAI" }],
      transcription_models: [],
      mcp_servers: [{ id: "mcp1", name: "Diariet" }],
      capabilities: ["web_search"],
      data_retention_days: 90
    },
    usage: {
      window_days: 30,
      threshold: 5,
      suppressed: false,
      questions: 1234,
      app_runs: 56,
      active_users: 42,
      widget_questions: 310,
      last_activity: "past_week",
      knowledge_bytes: 52_428_800
    },
    assistants: [
      assistant("Budgetassistenten", {
        widgets: [
          { id: "w1", name: "Fråga ekonomi", status: "draft", activation_requested_at: null }
        ]
      }),
      assistant("Ekonomi", { is_default: true, instructions: null, description: null })
    ],
    apps: [
      {
        id: "app1",
        name: "Protokollsammanfattaren",
        description: "Sammanfattar nämndprotokoll.",
        published: false,
        completion_model: { id: "m1", name: "GPT-5", hosting: "eu", org: "OpenAI" },
        transcription_model: null,
        instructions: "Sammanfatta protokollet i punktform.",
        data_retention_days: 30
      }
    ],
    group_chats: [
      {
        id: "gc1",
        name: "Budgetrådet",
        published: true,
        insight_enabled: false,
        assistant_count: 3
      }
    ],
    knowledge: [
      {
        id: "k1",
        name: "Budgethandboken",
        kind: "collection",
        integration_type: null,
        item_count: 48,
        size_bytes: 12_582_912,
        updated_at: "2026-09-10",
        website_url: null,
        update_interval: null,
        requires_login: false,
        auto_disabled: false,
        used_by: [{ id: "a-Budgetassistenten", name: "Budgetassistenten" }]
      },
      {
        id: "k2",
        name: "sundsvall.se/ekonomi",
        kind: "website",
        integration_type: null,
        item_count: 1,
        size_bytes: 204_800,
        updated_at: null,
        website_url: "https://sundsvall.se/ekonomi",
        update_interval: "weekly",
        requires_login: true,
        auto_disabled: true,
        used_by: []
      },
      {
        id: "k3",
        name: null,
        kind: "integration",
        integration_type: "onedrive",
        item_count: 7,
        size_bytes: 1_048_576,
        updated_at: "2026-08-01",
        website_url: null,
        update_interval: null,
        requires_login: false,
        auto_disabled: false,
        used_by: []
      },
      {
        id: "k4",
        name: null,
        kind: "integration",
        integration_type: "sharepoint",
        integration_item: "file",
        item_count: 1,
        size_bytes: 20_480,
        updated_at: "2026-09-24",
        website_url: null,
        update_interval: null,
        requires_login: false,
        auto_disabled: false,
        used_by: []
      }
    ],
    inherited_knowledge_count: 2,
    widgets: [
      {
        id: "w1",
        name: "Fråga ekonomi",
        status: "draft",
        assistant: { id: "a-Budgetassistenten", name: "Budgetassistenten" },
        activation_requested_at: "2026-09-21T08:00:00Z"
      },
      {
        id: "w2",
        name: "Fråga om taxor",
        status: "active",
        assistant: { id: "a-Budgetassistenten", name: "Budgetassistenten" },
        activation_requested_at: null
      }
    ],
    members: {
      users: [
        {
          id: "u-ada",
          username: "Ada Lind",
          email: "ada.lind@example.org",
          role: "admin",
          state: "active",
          is_tenant_admin: false,
          oversight_join: null
        },
        {
          id: "u-bo",
          username: null,
          email: "bo.ek@example.org",
          role: "viewer",
          state: "invited",
          is_tenant_admin: false,
          oversight_join: null
        }
      ],
      groups: [{ id: "g-stod", name: "Ekonomistöd", role: "editor", user_count: 12 }],
      member_count: 14,
      group_count: 1,
      admins: {
        manageable: true,
        count: 1,
        principals: [{ kind: "user", id: "u-ada", name: "Ada Lind" }]
      },
      viewer_membership: viewing
    },
    attention: [],
    ...patch
  };
}

function withMembership(membership: AdminSpaceViewerMembership, space = detail()) {
  return { ...space, members: { ...space.members, viewer_membership: membership } };
}

let shell: HTMLDivElement;

function renderPage(space: AdminSpaceDetail | null = detail(), securityEnabled = true) {
  // The app shell gives the page its height; without it the scrolling main area has none.
  shell = document.createElement("div");
  shell.className = "flex h-screen flex-col";
  document.body.append(shell);
  const data = (value: AdminSpaceDetail | null) =>
    ({ space: value, securityEnabled, user: { id: "me" } }) as never;
  const result = render(SpacePage, { target: shell, props: { data: data(space) } });
  return {
    ...result,
    reload: (next: AdminSpaceDetail | null) => result.rerender({ data: data(next) })
  };
}

const tabTrigger = (name: RegExp) => page.getByRole("tab", { name });
const bannerHeading = () => page.getByRole("heading", { level: 2, name: /^admin_spaces_banner_/ });

/** Resolves the ids in `aria-describedby` to the text they point at. */
function description(element: Element): string {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent?.replace(/\s+/g, " ").trim())
    .join(" | ");
}

async function openTab(name: RegExp) {
  // bits-ui tabs activate on pointerdown, which a synthetic click does not send.
  (tabTrigger(name).element() as HTMLElement).click();
  await expect.element(tabTrigger(name)).toHaveAttribute("aria-selected", "true");
}

async function axeViolations(context: Element | Document = document) {
  // Measure resting colours, not a hover the last click left behind.
  await userEvent.unhover(document.body);
  await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
  const result = await axe.run(context, {
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

/** The opaque colour of `layers` painted in order, bottom first. */
function paint(...layers: string[]): [number, number, number] {
  const context = document.createElement("canvas").getContext("2d")!;
  for (const layer of layers) {
    context.fillStyle = layer;
    context.fillRect(0, 0, 1, 1);
  }
  const [r, g, b] = context.getImageData(0, 0, 1, 1).data;
  return [r, g, b];
}

function contrast(a: [number, number, number], b: [number, number, number]) {
  const luminance = (rgb: [number, number, number]) => {
    const [r, g, b] = rgb.map((channel) => {
      const c = channel / 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

beforeEach(() => {
  vi.clearAllMocks();
  navigation.invalidate.mockResolvedValue(undefined);
  navigation.invalidateAll.mockResolvedValue(undefined);
  route.url = new URL("http://localhost/admin/spaces/space-1");
  route.state = {};
  i18n.catalog = null;
  delete document.documentElement.dataset.theme;
  document.body.classList.add("bg-primary");
});

afterEach(async () => {
  document.body.classList.remove("bg-primary");
  await page.viewport(1280, 720);
});

describe("a space in Admin → Ytor", () => {
  test("an administrator who is not a member sees what is hidden and can join", async () => {
    renderPage();

    await expect.element(page.getByRole("heading", { level: 1 })).toHaveTextContent("Ekonomi");
    await expect.element(bannerHeading()).toHaveTextContent("admin_spaces_banner_viewing_title");
    await expect.element(page.getByText("admin_spaces_banner_viewing_body")).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "admin_spaces_join_open" }))
      .toBeVisible();
    expect(page.getByRole("link", { name: "admin_spaces_open_space" }).elements()).toHaveLength(0);
  });

  test("a joined member sees the role, when they joined, and can open or leave the space", async () => {
    renderPage(withMembership(joined));

    await expect.element(bannerHeading()).toHaveTextContent("admin_spaces_banner_member_title");
    const banner = page.getByRole("region", { name: "admin_spaces_banner_member_title" });
    await expect
      .element(banner)
      .toHaveTextContent("admin_spaces_banner_your_role(space_role_viewer)");
    await expect.element(banner).toHaveTextContent(/admin_spaces_banner_joined\(/);
    await expect
      .element(page.getByRole("link", { name: "admin_spaces_open_space" }))
      .toHaveAttribute("href", "/spaces/space-1/overview");
    const leave = page.getByRole("button", { name: "admin_spaces_leave_open" });
    await expect.element(leave).toBeVisible();
    expect(leave.element().hasAttribute("aria-disabled")).toBe(false);
    expect(page.getByRole("button", { name: "admin_spaces_join_open" }).elements()).toHaveLength(0);
  });

  test("a member through a group sees the groups and may join with a higher role", async () => {
    renderPage(withMembership(viaGroup));

    await expect.element(bannerHeading()).toHaveTextContent("admin_spaces_banner_group_title");
    await expect
      .element(page.getByText(/admin_spaces_banner_group_role\(space_role_editor\|Ekonomistöd\)/))
      .toBeVisible();
    await expect.element(page.getByText(/admin_spaces_banner_group_join_hint/)).toBeVisible();
    await expect.element(page.getByRole("link", { name: "admin_spaces_open_space" })).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "admin_spaces_join_open" }))
      .toBeVisible();
  });

  test("the only administrator cannot leave: the button stays focusable and says why", async () => {
    renderPage(
      withMembership({ ...joined, role: "admin", direct_role: "admin", can_leave: false })
    );

    const leave = page.getByRole("button", { name: "admin_spaces_leave_open" });
    await expect.element(leave).toHaveAttribute("aria-disabled", "true");
    // It looks blocked too, like the other refused controls.
    expect(getComputedStyle(leave.element()).opacity).toBe("0.6");
    expect(description(leave.element())).toBe("admin_spaces_leave_last_admin");
    await expect.element(page.getByText("admin_spaces_leave_last_admin")).toBeVisible();

    (leave.element() as HTMLElement).click();
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(page.getByRole("alertdialog").elements()).toHaveLength(0);
  });

  test("leaving with a role through a group says the access stays", async () => {
    renderPage(
      withMembership({
        ...joined,
        role: "editor",
        group_role: "editor",
        via_groups: [{ id: "g-stod", name: "Ekonomistöd" }]
      })
    );

    await page.getByRole("button", { name: "admin_spaces_leave_open" }).click();
    await expect
      .element(page.getByRole("alertdialog"))
      .toHaveAccessibleDescription("admin_spaces_leave_body_group(space_role_editor|Ekonomistöd)");
  });

  test("leaving asks first, then reloads, confirms and puts focus on the banner", async () => {
    admin.leave.mockResolvedValue({});
    const { reload } = renderPage(withMembership(joined));
    navigation.invalidateAll.mockImplementation(async () => {
      await reload(withMembership(viewing));
    });

    await page.getByRole("button", { name: "admin_spaces_leave_open" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog).toHaveAccessibleName("admin_spaces_leave_title(Ekonomi)");
    await expect.element(page.getByRole("button", { name: "cancel" })).toHaveFocus();
    await page.getByRole("button", { name: "admin_spaces_leave_confirm" }).click();

    await expect.element(dialog).not.toBeInTheDocument();
    expect(admin.leave).toHaveBeenCalledWith({ spaceId: "space-1" });
    expect(toast.success).toHaveBeenCalledWith("admin_spaces_left(Ekonomi)");
    await expect.element(bannerHeading()).toHaveTextContent("admin_spaces_banner_viewing_title");
    await vi.waitFor(() => expect(document.activeElement).toBe(bannerHeading().element()));
  });

  test("a space without an administrator says so and leads to its members", async () => {
    renderPage(
      detail({
        attention: ["no_admin"],
        members: {
          ...detail().members,
          admins: { manageable: false, count: 0, principals: [] }
        }
      })
    );

    const callout = page.getByRole("region", { name: "admin_spaces_no_admin_title" });
    await expect.element(callout).toHaveTextContent("admin_spaces_no_admin_body");
    expect(callout.element().closest("[role=alert], [aria-live]")).toBeNull();
    await page.getByRole("button", { name: "admin_spaces_no_admin_action" }).click();

    await expect.element(tabTrigger(/^members/)).toHaveAttribute("aria-selected", "true");
    await expect.element(page.getByRole("heading", { level: 2, name: "members" })).toHaveFocus();
  });

  /** The summary's `dd` for the `dt` whose text starts with `term`. */
  function fact(term: string) {
    const summary = page.getByRole("region", { name: "admin_spaces_summary_title" }).element();
    const dt = [...summary.querySelectorAll("dt")].find((element) =>
      element.textContent?.trim().startsWith(term)
    );
    return dt?.nextElementSibling?.textContent?.replace(/\s+/g, " ").trim();
  }

  test("the summary holds back each small number and says why", async () => {
    renderPage(
      detail({
        usage: {
          ...detail().usage,
          suppressed: true,
          questions: null,
          active_users: null,
          app_runs: null
        }
      })
    );

    await expect.element(page.getByText("admin_spaces_suppressed_help(5)")).toBeVisible();
    expect(fact("admin_spaces_fact_questions")).toBe("admin_spaces_suppressed_questions(5)");
    expect(fact("admin_spaces_fact_active_users")).toBe("admin_spaces_suppressed(5)");
    expect(fact("admin_spaces_fact_app_runs")).toBe("admin_spaces_suppressed_app_runs(5)");
    // Widget questions are not a count of people; they are shown once a widget has been public.
    expect(fact("admin_spaces_fact_widget_questions")).toBe("310");
    // One dd per dt, each pair in its own div.
    const summary = page.getByRole("region", { name: "admin_spaces_summary_title" }).element();
    const groups = summary.querySelectorAll("dl > div");
    expect([...groups].every((group) => group.querySelectorAll("dt, dd").length === 2)).toBe(true);
  });

  test("one person's count is hidden while the others are shown", async () => {
    // Four people ran apps and one asked every question.
    renderPage(
      detail({
        usage: {
          ...detail().usage,
          suppressed: true,
          questions: null,
          app_runs: 4,
          active_users: 5
        }
      })
    );

    expect(fact("admin_spaces_fact_questions")).toBe("admin_spaces_suppressed_questions(5)");
    expect(fact("admin_spaces_fact_app_runs")).toBe("4");
    expect(fact("admin_spaces_fact_active_users")).toBe("5");
  });

  test("a space without apps says nothing about held-back figures when it shows every one", async () => {
    // The API holds back app runs, which this space has no apps to show.
    renderPage(
      detail({
        apps: [],
        usage: { ...detail().usage, suppressed: true, app_runs: null }
      })
    );

    expect(fact("admin_spaces_fact_questions")).toBe("1 234");
    expect(fact("admin_spaces_fact_active_users")).toBe("42");
    expect(fact("admin_spaces_fact_app_runs")).toBeUndefined();
    expect(page.getByText("admin_spaces_suppressed_help(5)").query()).toBeNull();
  });

  test("a space without apps still explains a figure it holds back", async () => {
    renderPage(
      detail({
        apps: [],
        usage: { ...detail().usage, suppressed: true, active_users: null, app_runs: null }
      })
    );

    await expect.element(page.getByText("admin_spaces_suppressed_help(5)")).toBeVisible();
    expect(fact("admin_spaces_fact_active_users")).toBe("admin_spaces_suppressed(5)");
  });

  test("widget questions wait until a widget has been public, and say so", async () => {
    renderPage(detail({ usage: { ...detail().usage, widget_questions: null } }));

    expect(fact("admin_spaces_fact_widget_questions")).toBe("admin_spaces_widget_questions_hidden");
    expect(fact("admin_spaces_fact_questions")).toBe("1 234");
  });

  test("no recorded activity says it counts what retention has left", async () => {
    renderPage(detail({ usage: { ...detail().usage, last_activity: "none" } }));

    expect(fact("admin_spaces_col_last_active")).toBe(
      "admin_spaces_activity_none admin_spaces_activity_none_help"
    );
  });

  test("the tabs are named by the space, carry counts and follow ?tab=", async () => {
    route.url = new URL("http://localhost/admin/spaces/space-1?tab=knowledge");
    renderPage();

    await expect.element(page.getByRole("tablist")).toHaveAccessibleName("Ekonomi");
    await expect.element(tabTrigger(/^knowledge/)).toHaveAttribute("aria-selected", "true");
    // The people with access, as in the summary: not the number of rows.
    await expect.element(tabTrigger(/^members/)).toHaveAccessibleName("members 14");
    await expect
      .element(page.getByRole("heading", { level: 2, name: "admin_spaces_knowledge_title" }))
      .toBeVisible();

    await openTab(/^admin_spaces_tab_assistants/);
    await vi.waitFor(() => expect(navigation.replaceState).toHaveBeenCalled());
    expect(String(navigation.replaceState.mock.lastCall?.[0])).toContain("tab=assistants");
  });

  test("Back and Forward bring back the tab the history entry was left on", async () => {
    // SvelteKit restores the entry's shallow state but not the query it was left with.
    route.state = { tab: "widgets" };
    renderPage();

    await expect.element(tabTrigger(/^widget_admin_nav/)).toHaveAttribute("aria-selected", "true");
    await openTab(/^members/);
    await vi.waitFor(() => expect(navigation.replaceState).toHaveBeenCalled());
    const [url, state] = navigation.replaceState.mock.lastCall ?? [];
    expect(String(url)).toContain("tab=members");
    expect(state).toEqual({ tab: "members" });
  });

  test.each(["light", "dark"] as const)(
    "the selected tab stands out from the others (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      renderPage();
      await userEvent.unhover(document.body);
      await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));

      const selected = getComputedStyle(tabTrigger(/^settings/).element());
      const list = getComputedStyle(page.getByRole("tablist").element());
      const surface = getComputedStyle(document.body).backgroundColor;
      const behind = paint(surface, list.backgroundColor);
      const border = paint(
        surface,
        list.backgroundColor,
        selected.backgroundColor,
        selected.borderTopColor
      );
      // WCAG 1.4.11: the selection indicator needs 3:1 against what is next to it.
      expect(contrast(border, behind)).toBeGreaterThanOrEqual(3);
    }
  );

  test("a tab panel shows where keyboard focus is", async () => {
    renderPage();
    (tabTrigger(/^settings/).element() as HTMLElement).focus();
    await userEvent.keyboard("{Tab}");

    const panel = page.getByRole("tabpanel").element();
    expect(document.activeElement).toBe(panel);
    expect(getComputedStyle(panel).boxShadow).not.toBe("none");
  });

  test("every tab panel starts with its own heading", async () => {
    renderPage();
    const tabs: [RegExp, string][] = [
      [/^settings/, "settings"],
      [/^admin_spaces_tab_assistants/, "assistants"],
      [/^knowledge/, "admin_spaces_knowledge_title"],
      [/^members/, "members"],
      [/^widget_admin_nav/, "widget_admin_nav"]
    ];
    for (const [trigger, heading] of tabs) {
      await openTab(trigger);
      const panel = page.getByRole("tabpanel").element();
      const first = panel.querySelector("h1, h2, h3, h4, p, ul, table, dl");
      expect(first?.tagName, heading).toBe("H2");
      expect(first?.textContent?.trim()).toBe(heading);
    }
  });

  test("instructions stay collapsed until asked for, per assistant", async () => {
    renderPage();
    await openTab(/^admin_spaces_tab_assistants/);

    const show = page.getByRole("button", {
      name: "admin_spaces_show_instructions_named(Budgetassistenten)"
    });
    await expect.element(show).toHaveAttribute("aria-expanded", "false");
    await show.click();
    await expect
      .element(
        page.getByRole("button", {
          name: "admin_spaces_hide_instructions_named(Budgetassistenten)"
        })
      )
      .toHaveAttribute("aria-expanded", "true");
    await expect.element(page.getByText(/Svara kort och sakligt/)).toBeVisible();
    // The default assistant has none and is listed last.
    const cards = page.getByRole("article").elements();
    expect(cards.map((card) => card.querySelector("h3")?.textContent?.trim())).toEqual([
      "Budgetassistenten",
      "Ekonomi",
      "Protokollsammanfattaren"
    ]);
    await expect
      .element(page.getByRole("table", { name: "admin_spaces_group_chats_caption" }))
      .toBeVisible();
  });

  test("the knowledge tab names neither a OneDrive folder nor a SharePoint file", async () => {
    renderPage();
    await openTab(/^knowledge/);

    const table = page.getByRole("table", { name: "admin_spaces_knowledge_caption" });
    await expect.element(table).toBeVisible();
    await expect
      .element(page.getByRole("rowheader", { name: /admin_spaces_onedrive_name/ }))
      .toBeVisible();
    await expect
      .element(page.getByRole("rowheader", { name: /admin_spaces_sharepoint_file/ }))
      .toBeVisible();
    // Updates are days: no time of day, and never moved by the viewer's time zone.
    const updated = table.element().querySelector('time[datetime="2026-09-24"]');
    expect(updated?.textContent).toBe(
      new Intl.DateTimeFormat("sv-SE", { dateStyle: "medium", timeZone: "UTC" }).format(
        Date.UTC(2026, 8, 24)
      )
    );
    await expect
      .element(page.getByRole("rowheader", { name: /sundsvall\.se\/ekonomi/ }))
      .toHaveTextContent("admin_spaces_meta_never_updated");
    await expect.element(table).toHaveTextContent("admin_spaces_requires_login");
    await expect.element(table).toHaveTextContent("admin_spaces_auto_disabled");
    await expect.element(page.getByText("admin_spaces_inherited(2)")).toBeVisible();
  });

  test("the widgets tab links each widget to its review", async () => {
    renderPage();
    await openTab(/^widget_admin_nav/);

    await expect
      .element(page.getByRole("link", { name: "Fråga ekonomi" }))
      .toHaveAttribute("href", "/admin/widgets/w1");
    await expect
      .element(page.getByRole("table", { name: "admin_spaces_widgets_caption" }))
      .toHaveTextContent("widget_admin_status_draft");
    // A live widget has no request to speak of.
    const live = page.getByRole("row", { name: /^Fråga om taxor/ }).element();
    expect(live.textContent).toContain("admin_spaces_activation_not_applicable");
    expect(live.textContent).not.toContain("admin_spaces_widget_not_requested");
  });

  test("a space that is gone, personal or the organisation space gets its own page", async () => {
    renderPage(null);

    await expect
      .element(page.getByRole("heading", { level: 1 }))
      .toHaveTextContent("admin_spaces_not_found_title");
    await expect.element(page.getByText("admin_spaces_not_found_body")).toBeVisible();
    await expect
      .element(page.getByRole("link", { name: "admin_spaces_back" }))
      .toHaveAttribute("href", "/admin/spaces");
    expect(page.getByRole("tablist").elements()).toHaveLength(0);
  });

  test.each([320, 1440])(
    "every tab reflows at %i px without scrolling sideways, in Swedish",
    async (width) => {
      i18n.catalog = sv;
      await page.viewport(width, 900);
      renderPage(
        withMembership(
          viaGroup,
          detail({ attention: ["no_admin"], name: "Utbildningsförvaltningens vuxenutbildning" })
        )
      );

      // The name wraps instead of being cut off.
      const title = page.getByRole("heading", { level: 1 }).element() as HTMLElement;
      await expect.element(title).toHaveTextContent("Utbildningsförvaltningens vuxenutbildning");
      expect(title.scrollWidth).toBeLessThanOrEqual(title.clientWidth);

      for (const name of [
        /^Inställningar/,
        /^Assistenter och appar/,
        /^Kunskap/,
        /^Medlemmar/,
        /^Webbwidgetar/
      ]) {
        await openTab(name);
        expect(horizontalOverflow(), String(name)).toEqual([]);
      }
    }
  );

  test.each(["light", "dark"] as const)(
    "every tab passes every WCAG 2.2 A and AA rule (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      await page.viewport(1440, 900);
      renderPage(withMembership(joined, detail({ attention: ["no_admin"] })));

      for (const name of [
        /^settings/,
        /^admin_spaces_tab_assistants/,
        /^knowledge/,
        /^members/,
        /^widget_admin_nav/
      ]) {
        await openTab(name);
        expect(await axeViolations(), String(name)).toEqual([]);
      }
    }
  );
});
