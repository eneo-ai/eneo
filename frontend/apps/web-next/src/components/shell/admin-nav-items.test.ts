import { describe, expect, it } from "vitest";
import { adminNavGroups } from "./admin-nav-items";

describe("adminNavGroups", () => {
  it("gives every item its own icon, so the icon rail tells them apart", () => {
    const items = adminNavGroups({
      usingTemplates: true,
      canManageModules: true
    }).flatMap((group) => group.items);
    expect(new Set(items.map((item) => item.icon)).size).toBe(items.length);
  });
});
