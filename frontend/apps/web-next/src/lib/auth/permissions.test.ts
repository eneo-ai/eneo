import { describe, expect, it } from "vitest";
import { collectPermissions, hasPermission, type Permission } from "./permissions";

function user(...rolePermissions: Permission[][]) {
  return { roles: rolePermissions.map((permissions) => ({ permissions })) };
}

describe("collectPermissions", () => {
  it("flattens roles and predefined_roles", () => {
    const permissions = collectPermissions({
      roles: [{ permissions: ["assistants"] }],
      predefined_roles: [{ permissions: ["admin"] }]
    });
    expect(permissions).toEqual(["assistants", "admin"]);
  });

  it("tolerates missing or null role lists", () => {
    expect(collectPermissions({})).toEqual([]);
    expect(collectPermissions({ roles: null })).toEqual([]);
    expect(collectPermissions({ roles: [{ permissions: null }] })).toEqual([]);
  });
});

describe("hasPermission", () => {
  it("checks a single permission", () => {
    const can = hasPermission(user(["assistants", "apps"]));
    expect(can("assistants")).toBe(true);
    expect(can("admin")).toBe(false);
  });

  it("null requirement always passes", () => {
    expect(hasPermission(user([]))(null)).toBe(true);
  });

  it("anyOf passes when at least one permission matches", () => {
    const can = hasPermission(user(["apps"]));
    expect(can({ anyOf: ["assistants", "apps"] })).toBe(true);
    expect(can({ anyOf: ["assistants", "services"] })).toBe(false);
  });

  it("allOf requires every permission", () => {
    const can = hasPermission(user(["assistants"], ["apps"]));
    expect(can({ allOf: ["assistants", "apps"] })).toBe(true);
    expect(can({ allOf: ["assistants", "admin"] })).toBe(false);
  });

  it("combines allOf and anyOf", () => {
    const can = hasPermission(user(["assistants", "apps"]));
    expect(can({ allOf: ["assistants"], anyOf: ["apps", "admin"] })).toBe(true);
    expect(can({ allOf: ["admin"], anyOf: ["apps"] })).toBe(false);
    expect(can({ allOf: ["assistants"], anyOf: ["admin"] })).toBe(false);
  });

  it("empty roles deny plain permissions", () => {
    const can = hasPermission({ roles: [] });
    expect(can("assistants")).toBe(false);
    expect(can({ anyOf: ["assistants"] })).toBe(false);
    expect(can({ allOf: [] })).toBe(true);
  });
});
