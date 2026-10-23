import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type Role = Schema<"RolePublic">;
export type Permission = Schema<"Permission">;
export type PermissionEntry = Schema<"PermissionPublic">;
export type RoleTemplate = { name: string; permissions: Permission[] };
export type PermissionGroupId = "chat" | "build" | "knowledge" | "insight" | "admin" | "other";
export type PermissionGroup = { id: PermissionGroupId; permissions: PermissionEntry[] };

export const ROLES_KEY = ["roles"] as const;

/** Shared by the role manager and the user role picker. */
export function rolesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ROLES_KEY,
    queryFn: async (): Promise<{ predefined: Role[]; custom: Role[] }> => {
      const response = await unwrap(api.GET("/api/v1/roles/"));
      return { predefined: response.predefined_roles.items, custom: response.roles.items };
    }
  });
}

export function permissionsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["role-permissions"],
    queryFn: () => unwrap(api.GET("/api/v1/roles/permissions/"))
  });
}

/** The templates endpoint has no generated schema. Reject malformed data rather than silently changing grants. */
export function parseRoleTemplates(
  value: unknown,
  catalogue: readonly PermissionEntry[]
): RoleTemplate[] {
  if (!Array.isArray(value)) throw new Error("Invalid role template response");
  return value.map((item: unknown) => {
    if (
      typeof item !== "object" ||
      item === null ||
      !("name" in item) ||
      typeof item.name !== "string" ||
      !("permissions" in item) ||
      !Array.isArray(item.permissions)
    )
      throw new Error("Invalid role template");
    const permissions = item.permissions.map((value: unknown) => {
      const match = catalogue.find((entry) => entry.name === value);
      if (!match) throw new Error("Unknown role template permission");
      return match.name;
    });
    return { name: item.name, permissions };
  });
}

export function templatesQueryOptions(api: EneoClient, catalogue: readonly PermissionEntry[]) {
  return queryOptions({
    queryKey: ["role-templates"],
    queryFn: async () =>
      parseRoleTemplates(await unwrap(api.GET("/api/v1/roles/templates/")), catalogue)
  });
}

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

export function groupPermissions(catalogue: readonly PermissionEntry[]): PermissionGroup[] {
  const byName = new Map<string, PermissionEntry>(catalogue.map((entry) => [entry.name, entry]));
  const placed = new Set<string>();
  return ORDER.map((id) => {
    const names =
      id === "other"
        ? catalogue.map((entry) => entry.name).filter((name) => !placed.has(name))
        : MEMBERS[id].filter((name) => byName.has(name));
    const permissions = names.map((name) => {
      const entry = byName.get(name);
      if (!entry) throw new Error(`Missing permission ${name}`);
      placed.add(name);
      return entry;
    });
    return { id, permissions };
  }).filter((group) => group.permissions.length > 0);
}

export function sameSet(a: readonly string[], b: readonly string[]): boolean {
  const left = new Set(a);
  const right = new Set(b);
  return left.size === right.size && [...left].every((value) => right.has(value));
}

export function sortRoles(
  roles: readonly Role[],
  defaultRoleId: string | null,
  locale: string
): Role[] {
  return [...roles].sort((a, b) => {
    if (a.id === defaultRoleId) return -1;
    if (b.id === defaultRoleId) return 1;
    if (a.permissions.length !== b.permissions.length)
      return b.permissions.length - a.permissions.length;
    return a.name.localeCompare(b.name, locale);
  });
}

export function roleMatches(
  role: Role,
  groups: readonly PermissionGroup[],
  query: string,
  labelFor: (entry: PermissionEntry) => string
): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle || role.name.toLocaleLowerCase().includes(needle)) return true;
  const held = new Set(role.permissions);
  return groups.some((group) =>
    group.permissions.some(
      (entry) => held.has(entry.name) && labelFor(entry).toLocaleLowerCase().includes(needle)
    )
  );
}
