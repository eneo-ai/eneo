import { describe, expect, test, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>(
    {},
    {
      get: (_target, key) => () => String(key)
    }
  )
}));

import type { Permission } from "@eneo/eneo-js";
import { groupPermissions, roleMatches, sameSet, summarizeGroups } from "./permission-groups";

const catalogue = (
  [
    "assistants",
    "skills",
    "skills_management",
    "personal_chat",
    "group_chats",
    "apps",
    "services",
    "collections",
    "websites",
    "insights",
    "integrations",
    "AI",
    "admin",
    "shared_spaces",
    "api_keys",
    "storage",
    "modules",
    "assistant_debug",
    "web_search",
    "image_generation"
  ] as Permission[]
).map((name) => ({ name, description: `${name} description` }));

describe("groupPermissions", () => {
  test("places every catalogue entry in exactly one group, in display order", () => {
    const groups = groupPermissions(catalogue);

    expect(groups.map((group) => group.id)).toEqual([
      "chat",
      "build",
      "knowledge",
      "insight",
      "admin"
    ]);
    const names = groups.flatMap((group) => group.permissions.map((p) => p.name));
    expect(new Set(names).size).toBe(catalogue.length);
    expect(names).toHaveLength(catalogue.length);
    expect(groups[0].permissions.map((p) => p.name)).toEqual([
      "personal_chat",
      "group_chats",
      "shared_spaces",
      "web_search",
      "image_generation"
    ]);
  });

  test("labels come from the translation catalogue, not from the backend key", () => {
    const [chat] = groupPermissions(catalogue);
    expect(chat.label).toBe("permission_group_chat");
    expect(chat.shortLabel).toBe("permission_group_chat_short");
    expect(chat.permissions[0]).toMatchObject({
      name: "personal_chat",
      label: "permission_personal_chat",
      description: "permission_personal_chat_description"
    });
  });

  test("keys the frontend does not know yet land in 'other' with a readable fallback", () => {
    const groups = groupPermissions([
      ...catalogue,
      { name: "time_travel" as Permission, description: "Bend time." }
    ]);
    const other = groups.at(-1);
    expect(other?.id).toBe("other");
    expect(other?.permissions).toEqual([
      { name: "time_travel", label: "Time travel", description: "Bend time." }
    ]);
  });

  test("drops groups that have no permissions in the catalogue", () => {
    const groups = groupPermissions(catalogue.filter((p) => p.name === "admin"));
    expect(groups.map((group) => group.id)).toEqual(["admin"]);
  });
});

describe("summarizeGroups", () => {
  test("counts granted permissions per group", () => {
    const groups = groupPermissions(catalogue);
    const summary = summarizeGroups(groups, ["personal_chat", "web_search", "admin"]);

    expect(summary.map(({ id, granted, total }) => [id, granted, total])).toEqual([
      ["chat", 2, 5],
      ["build", 0, 6],
      ["knowledge", 0, 3],
      ["insight", 0, 2],
      ["admin", 1, 4]
    ]);
  });
});

describe("roleMatches", () => {
  const groups = groupPermissions(catalogue);

  test("matches on the role name regardless of case and surrounding whitespace", () => {
    expect(roleMatches({ name: "AI Configurator", permissions: [] }, groups, "  config ")).toBe(
      true
    );
    expect(roleMatches({ name: "Owner", permissions: [] }, groups, "config")).toBe(false);
  });

  test("matches on the label of a permission the role grants, but not one it lacks", () => {
    const role = { name: "Reader", permissions: ["api_keys"] };
    expect(roleMatches(role, groups, "permission_api_keys")).toBe(true);
    expect(roleMatches(role, groups, "permission_admin")).toBe(false);
  });

  test("an empty query matches everything", () => {
    expect(roleMatches({ name: "x", permissions: [] }, groups, "")).toBe(true);
  });
});

describe("sameSet", () => {
  test("ignores order and duplicates", () => {
    expect(sameSet(["a", "b", "b"], ["b", "a"])).toBe(true);
    expect(sameSet(["a"], ["a", "b"])).toBe(false);
  });
});
