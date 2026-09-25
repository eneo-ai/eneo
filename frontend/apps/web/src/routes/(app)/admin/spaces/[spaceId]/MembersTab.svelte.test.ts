import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { EneoError, type AdminSpaceMembers } from "@eneo/eneo-js";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import sv from "../../../../../../messages/sv.json";
import "../../../../../app.css";

const navigation = vi.hoisted(() => ({ invalidate: vi.fn() }));
const api = vi.hoisted(() => ({
  members: { add: vi.fn(), update: vi.fn(), remove: vi.fn() },
  groupMembers: { add: vi.fn(), update: vi.fn(), remove: vi.fn() },
  users: vi.fn(),
  groups: vi.fn()
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
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
  replaceState: vi.fn()
}));
vi.mock("$app/state", () => ({
  page: { url: new URL("http://localhost/admin/spaces/space-1?tab=members"), state: {} }
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    spaces: { admin: { members: api.members, groupMembers: api.groupMembers } },
    users: { list: api.users },
    userGroups: { list: api.groups }
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

import MembersTab from "./MembersTab.svelte";

function members(patch: Partial<AdminSpaceMembers> = {}): AdminSpaceMembers {
  return {
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
        id: "me",
        username: "Olle Nilsson",
        email: "olle@example.org",
        role: "viewer",
        state: "active",
        is_tenant_admin: true,
        oversight_join: { joined_at: "2026-09-20T09:00:00Z", reason: "Ärende 2026-114" }
      },
      {
        id: "u-bo",
        username: null,
        email: "bo.ek@example.org",
        role: "editor",
        state: "inactive",
        is_tenant_admin: false,
        oversight_join: null
      }
    ],
    groups: [{ id: "g-stod", name: "Ekonomistöd", role: "viewer", user_count: 12 }],
    member_count: 15,
    group_count: 1,
    admins: {
      manageable: true,
      count: 1,
      principals: [{ kind: "user", id: "u-ada", name: "Ada Lind" }]
    },
    viewer_membership: {
      role: "viewer",
      direct_role: "viewer",
      via_groups: [],
      joinable_roles: [],
      can_leave: true
    },
    ...patch
  };
}

function renderTab(value = members()) {
  return render(MembersTab, {
    space: { id: "space-1", name: "Ekonomi", members: value },
    currentUserId: "me"
  });
}

const role = (name: string) =>
  page.getByRole("button", { name: new RegExp(`^admin_spaces_role_for\\(${name}\\) `) });
const remove = (name: string) =>
  page.getByRole("button", { name: `admin_spaces_remove_named(${name})`, exact: true });
/** Toasts are live regions; a second announcement of the same change would repeat it. */
const liveRegions = () => page.getByRole("status").elements();

/** Resolves the ids in `aria-describedby` to the text they point at. */
function description(element: Element): string {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent?.replace(/\s+/g, " ").trim())
    .join(" | ");
}

async function axeViolations(context: Element | Document = document) {
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

beforeEach(() => {
  vi.clearAllMocks();
  navigation.invalidate.mockResolvedValue(undefined);
  api.users.mockResolvedValue({
    items: [
      { id: "u-ada", email: "ada.lind@example.org", username: "Ada Lind" },
      { id: "me", email: "olle@example.org", username: "Olle Nilsson" },
      { id: "u-cai", email: "cai.berg@example.org", username: "Cai Berg" }
    ],
    total_count: 3
  });
  api.groups.mockResolvedValue([
    { id: "g-stod", name: "Ekonomistöd" },
    { id: "g-hr", name: "HR-gruppen" }
  ]);
  i18n.catalog = null;
  delete document.documentElement.dataset.theme;
  document.body.classList.add("bg-primary");
});

afterEach(async () => {
  document.body.classList.remove("bg-primary");
  await page.viewport(1280, 720);
});

describe("MembersTab", () => {
  test("names every control after its member and reads the role out with it", async () => {
    renderTab();

    await expect
      .element(role("Ada Lind"))
      .toHaveAccessibleName("admin_spaces_role_for(Ada Lind) space_role_admin");
    await expect
      .element(role("bo.ek@example.org"))
      .toHaveAccessibleName("admin_spaces_role_for(bo.ek@example.org) space_role_editor");
    await expect
      .element(role("Ekonomistöd"))
      .toHaveAccessibleName("admin_spaces_role_for(Ekonomistöd) space_role_viewer");
    await expect.element(remove("Ada Lind")).toBeVisible();
    await expect.element(remove("bo.ek@example.org")).toBeVisible();
    await expect.element(remove("Ekonomistöd")).toBeVisible();
    const names = [
      ...page.getByRole("button", { name: /^admin_spaces_(role_for|remove_named)/ }).elements()
    ].map((button) => button.getAttribute("aria-label") ?? button.textContent);
    expect(new Set(names).size).toBe(names.length);
  });

  test("the only administrator's controls stay focusable, are marked disabled and say why", async () => {
    renderTab();

    for (const control of [role("Ada Lind"), remove("Ada Lind")]) {
      await expect.element(control).toHaveAttribute("aria-disabled", "true");
      expect(description(control.element())).toBe("admin_spaces_only_admin");
    }
    await expect.element(page.getByText("admin_spaces_only_admin")).toBeVisible();
    expect(role("bo.ek@example.org").element().hasAttribute("aria-disabled")).toBe(false);
  });

  test("the administrator's own row shows the role as text and points to join and leave", async () => {
    renderTab();

    const own = page.getByRole("listitem").filter({ hasText: "Olle Nilsson" });
    await expect.element(own).toHaveTextContent("space_role_viewer");
    await expect.element(own).toHaveTextContent("admin_spaces_own_row_note");
    await expect.element(own).toHaveTextContent("(you)");
    expect(own.element().querySelectorAll("button")).toHaveLength(0);
    // Who joined through oversight, and why, is visible to the administrator.
    await expect.element(own).toHaveTextContent("admin_spaces_badge_tenant_admin");
    await expect.element(own).toHaveTextContent(/admin_spaces_badge_joined\(/);
    await expect.element(own).toHaveTextContent("space_oversight_notice_reason(Ärende 2026-114)");
    await expect
      .element(page.getByRole("listitem").filter({ hasText: "bo.ek@example.org" }))
      .toHaveTextContent("admin_spaces_badge_inactive");
  });

  test("a role change shows at once, is confirmed and announced once, and the page reloads", async () => {
    const saved = members();
    saved.users[2] = { ...saved.users[2], role: "admin" };
    api.members.update.mockResolvedValue(saved);
    renderTab();

    await role("bo.ek@example.org").click();
    await page.getByRole("option", { name: "space_role_admin" }).click();

    expect(api.members.update).toHaveBeenCalledWith({
      spaceId: "space-1",
      userId: "u-bo",
      role: "admin"
    });
    await expect
      .element(role("bo.ek@example.org"))
      .toHaveAccessibleName("admin_spaces_role_for(bo.ek@example.org) space_role_admin");
    expect(toast.success).toHaveBeenCalledExactlyOnceWith(
      "admin_spaces_role_changed(bo.ek@example.org|space_role_admin)"
    );
    expect(liveRegions()).toHaveLength(0);
    expect(navigation.invalidate).toHaveBeenCalledWith("admin:space");
  });

  test("a refused change puts the old role back and says why", async () => {
    api.groupMembers.update.mockRejectedValue(
      new EneoError("Last admin", "RESPONSE", 409, 9064, {})
    );
    renderTab();

    await role("Ekonomistöd").click();
    await page.getByRole("option", { name: "space_role_editor" }).click();

    await vi.waitFor(() => expect(toast.error).toHaveBeenCalledWith("eneo_error_9064"));
    await expect
      .element(role("Ekonomistöd"))
      .toHaveAccessibleName("admin_spaces_role_for(Ekonomistöd) space_role_viewer");
    expect(toast.success).not.toHaveBeenCalled();
    expect(navigation.invalidate).not.toHaveBeenCalled();
  });

  test("a member someone else removed first: the list is reloaded with an explanation", async () => {
    api.members.update.mockRejectedValue(new EneoError("Not found", "RESPONSE", 404, 0, {}));
    renderTab();

    await role("bo.ek@example.org").click();
    await page.getByRole("option", { name: "space_role_viewer" }).click();

    await vi.waitFor(() => expect(toast.info).toHaveBeenCalledWith("admin_spaces_members_changed"));
    expect(navigation.invalidate).toHaveBeenCalledWith("admin:space");
    await expect
      .element(role("bo.ek@example.org"))
      .toHaveAccessibleName("admin_spaces_role_for(bo.ek@example.org) space_role_editor");
    expect(toast.error).not.toHaveBeenCalled();
  });

  test("removing asks with the consequences, then moves focus to the list's heading", async () => {
    const after = members();
    after.users = after.users.filter((user) => user.id !== "u-bo");
    api.members.remove.mockResolvedValue(after);
    renderTab();

    await remove("bo.ek@example.org").click();
    const dialog = page.getByRole("alertdialog");
    await expect
      .element(dialog)
      .toHaveAccessibleName("admin_spaces_remove_title(bo.ek@example.org|Ekonomi)");
    await expect
      .element(dialog)
      .toHaveAccessibleDescription("admin_spaces_remove_body_person(bo.ek@example.org)");
    await expect.element(page.getByRole("button", { name: "cancel" })).toHaveFocus();
    await page.getByRole("button", { name: "remove", exact: true }).click();

    await expect.element(dialog).not.toBeInTheDocument();
    expect(api.members.remove).toHaveBeenCalledWith({ spaceId: "space-1", userId: "u-bo" });
    expect(page.getByText("bo.ek@example.org", { exact: true }).elements()).toHaveLength(0);
    await expect
      .element(page.getByRole("heading", { level: 3, name: "admin_spaces_people" }))
      .toHaveFocus();
    expect(toast.success).toHaveBeenCalledExactlyOnceWith(
      "admin_spaces_member_removed(bo.ek@example.org)"
    );
    expect(liveRegions()).toHaveLength(0);
  });

  test("counts people with access the same way as the rest of the page", async () => {
    const summary = () =>
      page.getByRole("heading", { level: 2, name: "members" }).element().nextElementSibling
        ?.textContent;
    const { rerender } = renderTab();
    await expect.element(page.getByRole("heading", { level: 2 })).toBeVisible();
    expect(summary()).toBe(
      "admin_spaces_members_summary(admin_spaces_count_people(15)|3|admin_spaces_count_groups_one)"
    );

    await rerender({
      space: { id: "space-1", name: "Ekonomi", members: members({ groups: [], member_count: 3 }) },
      currentUserId: "me"
    });
    expect(summary()).toBe("admin_spaces_members_summary_direct(admin_spaces_count_people(3))");

    await rerender({
      space: {
        id: "space-1",
        name: "Ekonomi",
        members: members({ users: [], member_count: 0 })
      },
      currentUserId: "me"
    });
    expect(summary()).toBe("admin_spaces_members_summary_none");
  });

  test("another organisation administrator can be lowered here but must join to go higher", async () => {
    const value = members();
    value.users.push({
      id: "u-tina",
      username: "Tina Ek",
      email: "tina.ek@example.org",
      role: "editor",
      state: "active",
      is_tenant_admin: true,
      oversight_join: null
    });
    renderTab(value);

    const picker = role("Tina Ek");
    expect(description(picker.element())).toBe("admin_spaces_tenant_admin_role_note");
    await picker.click();
    const offered = page
      .getByRole("option")
      .elements()
      .map((option) => option.textContent?.trim());
    expect(offered).toEqual(["space_role_viewer", "space_role_editor"]);
    await userEvent.keyboard("{Escape}");
    // Everyone else can still be given any role.
    await role("bo.ek@example.org").click();
    expect(page.getByRole("option").elements()).toHaveLength(3);
  });

  test("adding an organisation administrator explains that they join themselves", async () => {
    api.members.add.mockRejectedValue(new EneoError("Must join", "RESPONSE", 400, 9067, {}));
    renderTab();

    await page.getByRole("button", { name: "admin_spaces_add_person" }).click();
    await page.getByRole("button", { name: /^admin_spaces_person / }).click();
    await page.getByRole("option").filter({ hasText: "cai.berg@example.org" }).click();
    await page.getByRole("button", { name: "add", exact: true }).click();

    await expect
      .element(page.getByRole("alert"))
      .toHaveTextContent("admin_spaces_add_person_failed: eneo_error_9067");
    await expect.element(page.getByRole("dialog")).toBeVisible();
  });

  test("a group's removal says how many people it affects", async () => {
    renderTab();

    await remove("Ekonomistöd").click();
    await expect
      .element(page.getByRole("alertdialog"))
      .toHaveAccessibleDescription("admin_spaces_remove_body_group(12)");
  });

  test("the person picker offers neither oneself nor existing members", async () => {
    renderTab();

    await page.getByRole("button", { name: "admin_spaces_add_person" }).click();
    const dialog = page.getByRole("dialog");
    await expect.element(dialog).toHaveAccessibleName("admin_spaces_add_person_title(Ekonomi)");
    await page.getByRole("button", { name: /^admin_spaces_person / }).click();

    const option = (email: string) => page.getByRole("option").filter({ hasText: email });
    await expect.element(option("olle@example.org")).toHaveAttribute("aria-disabled", "true");
    await expect
      .element(option("olle@example.org"))
      .toHaveTextContent("admin_spaces_self_in_picker");
    await expect.element(option("ada.lind@example.org")).toHaveAttribute("aria-disabled", "true");
    await expect
      .element(option("ada.lind@example.org"))
      .toHaveTextContent("admin_spaces_already_member");
    expect(option("cai.berg@example.org").element().getAttribute("aria-disabled")).not.toBe("true");
  });

  test("adding a person waits for the server, then closes, confirms and announces", async () => {
    const after = members();
    after.users.push({
      id: "u-cai",
      username: "Cai Berg",
      email: "cai.berg@example.org",
      role: "viewer",
      state: "active",
      is_tenant_admin: false,
      oversight_join: null
    });
    api.members.add.mockResolvedValue(after);
    renderTab();

    await page.getByRole("button", { name: "admin_spaces_add_person" }).click();
    await page.getByRole("button", { name: /^admin_spaces_person / }).click();
    await page.getByRole("option").filter({ hasText: "cai.berg@example.org" }).click();
    // The lowest role is preselected.
    await expect
      .element(page.getByRole("button", { name: "role space_role_viewer" }))
      .toBeVisible();
    await page.getByRole("button", { name: "add", exact: true }).click();

    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
    expect(api.members.add).toHaveBeenCalledWith({
      spaceId: "space-1",
      userId: "u-cai",
      role: "viewer"
    });
    expect(toast.success).toHaveBeenCalledExactlyOnceWith(
      "admin_spaces_member_added(Cai Berg|space_role_viewer)"
    );
    expect(liveRegions()).toHaveLength(0);
    await expect
      .element(page.getByRole("button", { name: "admin_spaces_add_person" }))
      .toHaveFocus();
  });

  test("a refused addition stays in the dialog with the reason", async () => {
    api.groupMembers.add.mockRejectedValue(new EneoError("Self", "RESPONSE", 400, 9066, {}));
    renderTab();

    await page.getByRole("button", { name: "admin_spaces_add_group" }).click();
    await page.getByRole("button", { name: /^user_group / }).click();
    await page.getByRole("option").filter({ hasText: "HR-gruppen" }).click();
    await page.getByRole("button", { name: "add", exact: true }).click();

    await expect
      .element(page.getByRole("alert"))
      .toHaveTextContent("admin_spaces_add_group_failed: eneo_error_9066");
    await expect.element(page.getByRole("dialog")).toBeVisible();
    expect(toast.success).not.toHaveBeenCalled();
  });

  test("reflows at 320 px with full-width role controls, in Swedish", async () => {
    i18n.catalog = sv;
    await page.viewport(320, 800);
    const { container } = renderTab();
    await expect.element(page.getByRole("heading", { level: 2 })).toBeVisible();

    const width = document.documentElement.clientWidth;
    const outside = [...container.querySelectorAll<HTMLElement>("*")].filter(
      (element) => !element.closest(".sr-only") && element.getBoundingClientRect().right > width + 1
    );
    expect(outside.map((element) => element.outerHTML.slice(0, 80))).toEqual([]);
    const select = page
      .getByRole("button", { name: /^Roll för bo\.ek@example\.org:/ })
      .element()
      .getBoundingClientRect();
    expect(select.height).toBeGreaterThanOrEqual(44);
    expect(select.width).toBeGreaterThan(width / 2);
  });

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      renderTab();
      await expect.element(role("Ada Lind")).toBeVisible();
      expect(await axeViolations()).toEqual([]);

      // Scoped to the dialog while it is open: the page behind a modal is inert.
      await page.getByRole("button", { name: "admin_spaces_add_person" }).click();
      await expect.element(page.getByRole("dialog")).toBeVisible();
      expect(await axeViolations(page.getByRole("dialog").element())).toEqual([]);
      await userEvent.keyboard("{Escape}");
      await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();

      // The removal's confirm button is the destructive variant.
      await remove("bo.ek@example.org").click();
      await expect.element(page.getByRole("alertdialog")).toBeVisible();
      expect(await axeViolations(page.getByRole("alertdialog").element())).toEqual([]);
    }
  );
});
