import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, unknown>) => string>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)} ${JSON.stringify(params)}` : String(key)
    }
  )
}));

vi.mock("$app/paths", () => ({
  resolve: (route: string) => route
}));

import type { Permission, Role } from "@eneo/eneo-js";
import { groupPermissions } from "$lib/features/roles/permission-groups";
import RoleRow from "./RoleRow.svelte";

const catalogue = (
  [
    "personal_chat",
    "group_chats",
    "assistants",
    "apps",
    "collections",
    "admin",
    "api_keys"
  ] as Permission[]
).map((name) => ({ name, description: `${name} description` }));
const groups = groupPermissions(catalogue);

const role: Role = {
  id: "role-1",
  name: "Editor",
  permissions: ["personal_chat", "group_chats", "assistants"] as Permission[],
  predefined_source: "User"
};

function renderRow(overrides: Partial<{ role: Role; isDefault: boolean }> = {}) {
  const handlers = {
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onReset: vi.fn(),
    onSetDefault: vi.fn()
  };
  render(RoleRow, { role, groups, isDefault: false, ...handlers, ...overrides });
  return handlers;
}

describe("RoleRow", () => {
  test("summarises permissions per area with a screen-reader count", async () => {
    renderRow();

    const summary = page.getByRole("list", { name: "roles_group_summary_label" });
    await expect.element(summary).toBeVisible();
    const items = summary.element().querySelectorAll("li");
    expect([...items].map((item) => item.textContent?.replace(/\s+/g, " ").trim())).toEqual([
      'permission_group_chat_short 2/2 roles_group_count {"granted":2,"total":2}',
      'permission_group_build_short 1/2 roles_group_count {"granted":1,"total":2}',
      'permission_group_knowledge_short 0/1 roles_group_count {"granted":0,"total":1}',
      'permission_group_admin_short 0/2 roles_group_count {"granted":0,"total":2}'
    ]);
  });

  test("expands to the full grouped list and keeps aria-expanded in sync", async () => {
    renderRow();

    const toggle = page.getByRole("button", { name: 'roles_show_permissions {"name":"Editor"}' });
    await expect.element(toggle).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById(toggle.element().getAttribute("aria-controls")!)).toBeNull();

    await toggle.click();

    const expandedToggle = page.getByRole("button", {
      name: 'roles_hide_permissions {"name":"Editor"}'
    });
    await expect.element(expandedToggle).toHaveAttribute("aria-expanded", "true");
    const panel = document.getElementById(expandedToggle.element().getAttribute("aria-controls")!);
    expect(panel).not.toBeNull();
    const region = page.getByRole("region", { name: "permission_group_build" });
    await expect.element(region).toBeVisible();
    const text = region.element().textContent?.replace(/\s+/g, " ") ?? "";
    expect(text).toContain("roles_permission_included permission_assistants");
    expect(text).toContain("roles_permission_not_included permission_apps");
  });

  test("shows the template badge and offers a reset for template roles", async () => {
    const handlers = renderRow();

    await expect
      .element(page.getByRole("button", { name: /roles_template_badge_named \{"name":"User"\}/ }))
      .toBeVisible();
    await page.getByRole("button", { name: 'roles_more_actions {"name":"Editor"}' }).click();
    await page
      .getByRole("menuitem", { name: 'roles_reset_to_template_named {"name":"User"}' })
      .click();
    expect(handlers.onReset).toHaveBeenCalledWith(role);
  });

  test("the default role cannot be deleted or set as default again", async () => {
    renderRow({ isDefault: true });

    await expect.element(page.getByText("roles_default_badge")).toBeVisible();
    await page.getByRole("button", { name: 'roles_more_actions {"name":"Editor"}' }).click();
    await expect
      .element(page.getByRole("menuitem", { name: "delete_role" }))
      .toHaveAttribute("aria-disabled", "true");
    await expect.element(page.getByText("roles_cannot_delete_default")).toBeVisible();
    await expect
      .element(page.getByRole("menuitem", { name: "set_as_default_role" }))
      .not.toBeInTheDocument();
  });

  test("links to the users page filtered by the role", async () => {
    renderRow();

    await page.getByRole("button", { name: 'roles_more_actions {"name":"Editor"}' }).click();
    const link = page.getByRole("menuitem", { name: "roles_view_users" });
    await expect.element(link).toHaveAttribute("href", "/admin/users?role_id=role-1");
  });
});
