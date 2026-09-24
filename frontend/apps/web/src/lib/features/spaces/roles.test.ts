import { describe, expect, it, vi } from "vitest";
import en from "../../../../messages/en.json";
import sv from "../../../../messages/sv.json";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));

import {
  ROLE_RANK,
  SPACE_ROLES,
  lowestRole,
  sortRolesAscending,
  spaceRoleDescription,
  spaceRoleLabel
} from "./roles";

const catalogs = { en, sv } as Record<string, Record<string, string>>;

describe("space roles", () => {
  it("ranks viewer below editor below admin", () => {
    expect(ROLE_RANK.viewer).toBeLessThan(ROLE_RANK.editor);
    expect(ROLE_RANK.editor).toBeLessThan(ROLE_RANK.admin);
    expect(SPACE_ROLES).toEqual(["viewer", "editor", "admin"]);
  });

  it("orders roles lowest first and picks the lowest", () => {
    const roles = ["admin", "viewer", "editor"] as const;
    expect(sortRolesAscending(roles)).toEqual(["viewer", "editor", "admin"]);
    expect(roles).toEqual(["admin", "viewer", "editor"]);
    expect(lowestRole(["admin", "editor"])).toBe("editor");
    expect(lowestRole([])).toBeUndefined();
  });

  it("names and describes each role with its own message", () => {
    expect(SPACE_ROLES.map(spaceRoleLabel)).toEqual([
      "space_role_viewer",
      "space_role_editor",
      "space_role_admin"
    ]);
    expect(SPACE_ROLES.map(spaceRoleDescription)).toEqual([
      "space_role_viewer_description",
      "space_role_editor_description",
      "space_role_admin_description"
    ]);
  });

  it("falls back to the raw value for a role this build does not know", () => {
    expect(spaceRoleLabel("owner" as never)).toBe("owner");
  });

  it("uses the agreed Swedish role names", () => {
    expect([sv.space_role_admin, sv.space_role_editor, sv.space_role_viewer]).toEqual([
      "Administratör",
      "Redigerare",
      "Visare"
    ]);
  });

  it.each(Object.entries(catalogs))(
    "has a name and a description for every role (%s)",
    (_, messages) => {
      for (const role of SPACE_ROLES) {
        expect(messages[`space_role_${role}`]).toBeTruthy();
        expect(messages[`space_role_${role}_description`]).toBeTruthy();
      }
    }
  );
});
