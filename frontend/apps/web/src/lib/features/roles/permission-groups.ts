import type { Permission } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { getPermissionCopy } from "./permission-labels";

export type PermissionGroupId = "chat" | "build" | "knowledge" | "insight" | "admin" | "other";

export type PermissionEntry = { name: Permission; label: string; description: string };

export type PermissionGroup = {
  id: PermissionGroupId;
  label: string;
  shortLabel: string;
  permissions: PermissionEntry[];
};

export type GroupSummary = {
  id: PermissionGroupId;
  label: string;
  shortLabel: string;
  granted: number;
  total: number;
};

// Display order of the groups, and of the permissions inside each group.
// Keys the backend adds later land in "other" until they are placed here.
const MEMBERS: Record<Exclude<PermissionGroupId, "other">, readonly string[]> = {
  chat: ["personal_chat", "group_chats", "shared_spaces", "web_search", "image_generation"],
  build: ["assistants", "apps", "services", "skills", "skills_management", "AI"],
  knowledge: ["collections", "websites", "integrations"],
  insight: ["insights", "assistant_debug"],
  admin: ["admin", "api_keys", "storage", "modules", "widgets"]
};

const ORDER: readonly PermissionGroupId[] = [
  "chat",
  "build",
  "knowledge",
  "insight",
  "admin",
  "other"
];

function groupCopy(id: PermissionGroupId): { label: string; shortLabel: string } {
  switch (id) {
    case "chat":
      return { label: m.permission_group_chat(), shortLabel: m.permission_group_chat_short() };
    case "build":
      return { label: m.permission_group_build(), shortLabel: m.permission_group_build_short() };
    case "knowledge":
      return {
        label: m.permission_group_knowledge(),
        shortLabel: m.permission_group_knowledge_short()
      };
    case "insight":
      return {
        label: m.permission_group_insight(),
        shortLabel: m.permission_group_insight_short()
      };
    case "admin":
      return { label: m.permission_group_admin(), shortLabel: m.permission_group_admin_short() };
    case "other":
      return { label: m.permission_group_other(), shortLabel: m.permission_group_other_short() };
  }
}

/** Arrange the backend's permission catalogue into display groups. Empty groups are dropped. */
export function groupPermissions(
  catalogue: ReadonlyArray<{ name: Permission; description: string }>
): PermissionGroup[] {
  const byName = new Map(catalogue.map((permission) => [permission.name as string, permission]));
  const placed = new Set<string>();
  const groups: PermissionGroup[] = [];

  for (const id of ORDER) {
    const names =
      id === "other"
        ? catalogue.map((permission) => permission.name).filter((name) => !placed.has(name))
        : MEMBERS[id].filter((name) => byName.has(name));
    const permissions = names.map((name) => {
      const permission = byName.get(name)!;
      const copy = getPermissionCopy(permission.name, permission.description);
      placed.add(name);
      return { name: permission.name, label: copy.label, description: copy.description };
    });
    if (permissions.length > 0) groups.push({ id, ...groupCopy(id), permissions });
  }

  return groups;
}

export function summarizeGroups(
  groups: readonly PermissionGroup[],
  granted: ReadonlyArray<string>
): GroupSummary[] {
  const held = new Set(granted);
  return groups.map((group) => ({
    id: group.id,
    label: group.label,
    shortLabel: group.shortLabel,
    granted: group.permissions.filter((permission) => held.has(permission.name)).length,
    total: group.permissions.length
  }));
}

/** True when the query matches the role's name or the label of a permission it grants. */
export function roleMatches(
  role: { name: string; permissions: ReadonlyArray<string> },
  groups: readonly PermissionGroup[],
  query: string
): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  if (role.name.toLocaleLowerCase().includes(needle)) return true;
  const held = new Set(role.permissions);
  return groups.some((group) =>
    group.permissions.some(
      (permission) =>
        held.has(permission.name) && permission.label.toLocaleLowerCase().includes(needle)
    )
  );
}

export function sameSet(a: ReadonlyArray<string>, b: ReadonlyArray<string>): boolean {
  const left = new Set(a);
  const right = new Set(b);
  return left.size === right.size && [...left].every((value) => right.has(value));
}

/** Default role first, then the broadest roles, then by name. */
export function sortRoles<
  T extends { id: string; name: string; permissions: ReadonlyArray<string> }
>(roles: readonly T[], defaultRoleId: string | null, locale?: string): T[] {
  return [...roles].sort((a, b) => {
    if (a.id === defaultRoleId) return -1;
    if (b.id === defaultRoleId) return 1;
    if (a.permissions.length !== b.permissions.length) {
      return b.permissions.length - a.permissions.length;
    }
    return a.name.localeCompare(b.name, locale);
  });
}
