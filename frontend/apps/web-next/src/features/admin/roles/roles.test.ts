import { describe, expect, it } from "vitest";
import {
  groupPermissions,
  parseRoleTemplates,
  roleMatches,
  sameSet,
  sortRoles,
  type PermissionEntry,
  type Role
} from "./roles";

const catalogue: PermissionEntry[] = [
  { name: "admin", description: "Administer users" },
  { name: "personal_chat", description: "Use chat" },
  { name: "skills", description: "Use skills" }
];
const role = (id: string, name: string, permissions: Role["permissions"]): Role => ({
  id,
  name,
  permissions
});

describe("role catalogue", () => {
  it("groups permissions once, in the same display order as the existing app", () => {
    expect(
      groupPermissions(catalogue).map((group) => [
        group.id,
        group.permissions.map((entry) => entry.name)
      ])
    ).toEqual([
      ["chat", ["personal_chat"]],
      ["build", ["skills"]],
      ["admin", ["admin"]]
    ]);
  });

  it("searches granted permission labels and sorts the default role first", () => {
    const builder = role("b", "Builder", ["skills"]);
    const roles = [builder, role("a", "Admin", ["admin", "personal_chat"])];
    expect(sortRoles(roles, "b", "en").map((item) => item.id)).toEqual(["b", "a"]);
    expect(roleMatches(builder, groupPermissions(catalogue), "skill", (entry) => entry.name)).toBe(
      true
    );
    expect(roleMatches(builder, groupPermissions(catalogue), "admin", (entry) => entry.name)).toBe(
      false
    );
    expect(sameSet(["admin", "skills"], ["skills", "admin"])).toBe(true);
  });

  it("keeps template grants typed and rejects unknown or malformed grants", () => {
    expect(
      parseRoleTemplates([{ name: "Reader", permissions: ["personal_chat"] }], catalogue)
    ).toEqual([{ name: "Reader", permissions: ["personal_chat"] }]);
    expect(() =>
      parseRoleTemplates([{ name: "Reader", permissions: ["unknown"] }], catalogue)
    ).toThrow();
    expect(() => parseRoleTemplates({ name: "Reader" }, catalogue)).toThrow();
  });
});
