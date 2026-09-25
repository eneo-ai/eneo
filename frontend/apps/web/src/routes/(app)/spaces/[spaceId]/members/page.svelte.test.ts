import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { EneoError, type SpaceRoleValue } from "@eneo/eneo-js";
import type { Writable } from "svelte/store";
import { beforeEach, describe, expect, test, vi } from "vitest";
import "../../../../../app.css";

const api = vi.hoisted(() => ({
  members: { add: vi.fn(), update: vi.fn(), remove: vi.fn() },
  groupMembers: { add: vi.fn(), update: vi.fn(), remove: vi.fn() },
  users: vi.fn(),
  groups: vi.fn()
}));
const spaces = vi.hoisted(() => ({ refresh: vi.fn() }));
const errors = vi.hoisted(() => ({ toastError: vi.fn() }));
// The current space as SpacesManager's store; the mock factory creates it.
const current = vi.hoisted(() => ({ store: null as Writable<unknown> | null }));

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn()
}));
vi.mock("$app/state", () => ({
  page: { url: new URL("http://localhost/spaces/space-1/members"), state: {} }
}));
vi.mock("$lib/core/AppContext", () => ({ getAppContext: () => ({ user: { id: "me" } }) }));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    spaces: { members: api.members, groupMembers: api.groupMembers },
    users: { list: api.users },
    userGroups: { list: api.groups }
  })
}));
vi.mock("$lib/core/errors", async (importOriginal) => ({
  ...(await importOriginal<typeof import("$lib/core/errors")>()),
  toastError: errors.toastError
}));
vi.mock("$lib/features/spaces/SpacesManager", async () => {
  const { writable } = await import("svelte/store");
  current.store = writable(null);
  return {
    getSpacesManager: () => ({
      state: { currentSpace: current.store },
      refreshCurrentSpace: spaces.refresh
    })
  };
});
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)}(${Object.values(params).join("|")})` : String(key)
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));

import MembersPage from "./+page.svelte";

type Member = {
  id: string;
  email: string;
  username?: string;
  role: SpaceRoleValue;
  oversight_join?: { joined_at: string; reason?: string | null } | null;
};

const ada: Member = { id: "u-ada", email: "ada@example.org", role: "admin" };
const bo: Member = { id: "u-bo", email: "bo@example.org", role: "viewer" };
const olle: Member = {
  id: "u-olle",
  email: "olle@example.org",
  role: "viewer",
  oversight_join: { joined_at: "2026-09-20T09:00:00Z", reason: null }
};

/** The current space as SpacesManager hands it to the page. */
function space(members: Member[] = [ada, bo, olle]) {
  return {
    id: "space-1",
    name: "Ekonomi",
    members,
    group_members: {
      items: [{ id: "g-stod", name: "Ekonomistöd", role: "viewer", user_count: 4 }]
    },
    available_roles: [{ value: "admin" }, { value: "editor" }, { value: "viewer" }],
    hasPermission: () => true
  };
}

function renderPage() {
  // The app shell gives the page its height; without it the scrolling main area has none.
  const shell = document.createElement("div");
  shell.className = "flex h-screen flex-col";
  document.body.append(shell);
  return render(MembersPage, { target: shell });
}

const role = (name: string) =>
  page.getByRole("button", { name: new RegExp(`^admin_spaces_role_for\\(${name}\\)`) });

async function choose(name: string, option: string) {
  await role(name).click();
  await page.getByRole("option", { name: option }).click();
}

beforeEach(() => {
  vi.clearAllMocks();
  current.store!.set(space());
  spaces.refresh.mockResolvedValue(undefined);
  api.users.mockResolvedValue({
    items: [{ id: "u-cai", email: "cai@example.org", username: "Cai" }],
    total_count: 1
  });
  api.groups.mockResolvedValue([]);
});

describe("a space's members page", () => {
  test("a role change is saved through the space's own API, then the space reloads", async () => {
    api.members.update.mockResolvedValue({});
    renderPage();

    await choose("bo@example.org", "space_role_editor");

    await vi.waitFor(() => expect(spaces.refresh).toHaveBeenCalledTimes(1));
    expect(api.members.update).toHaveBeenCalledWith({
      spaceId: "space-1",
      user: { id: "u-bo", role: "editor" }
    });
    expect(errors.toastError).not.toHaveBeenCalled();
  });

  test("a refused role change is reported, puts the old role back and reloads nothing", async () => {
    const refusal = new EneoError("Last admin", "RESPONSE", 409, 9064, {});
    api.groupMembers.update.mockRejectedValue(refusal);
    renderPage();

    await choose("Ekonomistöd", "space_role_admin");

    await vi.waitFor(() =>
      expect(errors.toastError).toHaveBeenCalledWith(refusal, "couldnt_change_role")
    );
    await expect
      .element(role("Ekonomistöd"))
      .toHaveAccessibleName("admin_spaces_role_for(Ekonomistöd) space_role_viewer");
    expect(spaces.refresh).not.toHaveBeenCalled();
  });

  test("removing a member asks first, then removes them and reloads the space", async () => {
    api.members.remove.mockResolvedValue(undefined);
    renderPage();

    await page.getByRole("button", { name: "admin_spaces_remove_named(bo@example.org)" }).click();
    await expect
      .element(page.getByRole("alertdialog"))
      .toHaveAccessibleDescription("confirm_remove_member(bo@example.org)");
    await page.getByRole("button", { name: "remove", exact: true }).click();

    await vi.waitFor(() => expect(spaces.refresh).toHaveBeenCalledTimes(1));
    expect(api.members.remove).toHaveBeenCalledWith({
      spaceId: "space-1",
      user: expect.objectContaining({ id: "u-bo" })
    });
  });

  test("adding a person offers the lowest role first and reloads the space afterwards", async () => {
    api.members.add.mockResolvedValue(undefined);
    renderPage();

    await page.getByRole("button", { name: "add_new_member" }).click();
    await page.getByRole("button", { name: /^user / }).click();
    await page.getByRole("option").filter({ hasText: "cai@example.org" }).click();
    await expect
      .element(page.getByRole("button", { name: "role space_role_viewer" }))
      .toBeVisible();
    await page.getByRole("button", { name: "add_member", exact: true }).click();

    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
    expect(api.members.add).toHaveBeenCalledWith({
      spaceId: "space-1",
      user: { id: "u-cai", role: "viewer" }
    });
    expect(spaces.refresh).toHaveBeenCalledTimes(1);
  });

  test("an administrator who joined through oversight is named as one, in plain words", async () => {
    renderPage();

    const date = new Intl.DateTimeFormat("sv-SE", { dateStyle: "medium" }).format(
      new Date("2026-09-20T09:00:00Z")
    );
    await expect.element(page.getByText(`space_oversight_member_badge(${date})`)).toBeVisible();
    // Only the space's administrators get the reason; here there is none.
    expect(document.body.textContent).not.toContain("space_oversight_notice_reason");
  });
});
