import { describe, expect, it } from "vitest";
import { hasPermission } from "./hasPermission";

describe("hasPermission", () => {
  it("treats legacy flows as full flow access", () => {
    const can = hasPermission({
      roles: [{ id: "1", name: "Legacy Flow Role", permissions: ["flows"] }],
      predefined_roles: []
    });

    expect(can("flows_view")).toBe(true);
    expect(can("flows_run")).toBe(true);
    expect(can("flows_manage")).toBe(true);
    expect(can("flows_ai_builder")).toBe(true);
  });

  it("treats flows_manage as implying view and run", () => {
    const can = hasPermission({
      roles: [{ id: "1", name: "Flow Manager", permissions: ["flows_manage"] }],
      predefined_roles: []
    });

    expect(can("flows_view")).toBe(true);
    expect(can("flows_run")).toBe(true);
    expect(can("flows_manage")).toBe(true);
    expect(can("flows_ai_builder")).toBe(false);
  });

  it("requires both manage and ai builder for builder-only access checks", () => {
    const can = hasPermission({
      roles: [{ id: "1", name: "Builder Only", permissions: ["flows_ai_builder"] }],
      predefined_roles: []
    });

    expect(can({ allOf: ["flows_manage", "flows_ai_builder"] })).toBe(false);
  });

  it("denies all flow access when the user has no roles", () => {
    const can = hasPermission({
      roles: [],
      predefined_roles: []
    });

    expect(can("flows_view")).toBe(false);
    expect(can("flows_run")).toBe(false);
    expect(can("flows_manage")).toBe(false);
    expect(can("flows_ai_builder")).toBe(false);
  });
});
