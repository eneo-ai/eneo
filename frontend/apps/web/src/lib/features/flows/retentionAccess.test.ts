import { describe, expect, it } from "vitest";

import {
  adminHomeHref,
  canOpenAdmin,
  retentionAccess,
  retentionOnlyAllows
} from "./retentionAccess";

const access = (...granted: string[]) =>
  retentionAccess((permission) => granted.includes(permission));

describe("retention access", () => {
  it.each([
    [[], false],
    [["flows_manage"], false],
    [["admin"], true],
    [["retention_manage"], true],
    [["retention_holds"], true]
  ])("permissions %j open the admin area: %s", (granted, expected) => {
    expect(canOpenAdmin(access(...granted))).toBe(expected);
  });

  it("allows a retention-only role the retention tab of Flow settings and nothing else", () => {
    const allows = (href: string) => {
      const url = new URL(`http://localhost${href}`);
      return retentionOnlyAllows(url, url.pathname);
    };
    expect(allows("/admin/flow-settings")).toBe(true);
    expect(allows("/admin/flow-settings/")).toBe(true);
    expect(allows("/admin/flow-settings?tab=retention")).toBe(true);
    expect(allows("/admin/flow-settings?tab=uploads")).toBe(false);
    expect(allows("/admin/flow-settings?tab=builder")).toBe(false);
    expect(allows("/admin")).toBe(false);
    expect(allows("/admin/flow-settings-other")).toBe(false);
    expect(allows("/admin/users")).toBe(false);
  });

  it("points the main Admin link at the page each user may open", () => {
    expect(adminHomeHref(access("admin"))).toBe("/admin");
    expect(adminHomeHref(access("admin", "retention_holds"))).toBe("/admin");
    expect(adminHomeHref(access("retention_holds"))).toBe("/admin/flow-settings?tab=retention");
    expect(adminHomeHref(access("retention_manage"))).toBe("/admin/flow-settings?tab=retention");
  });
});
