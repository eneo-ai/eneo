import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/runtime", () => ({
  deLocalizeHref: (href: string) => href.replace(/^\/en(?=\/)/, ""),
  localizeHref: (href: string) => href
}));

import { load } from "./+layout";

function userWith(...permissions: string[]) {
  return { roles: [{ permissions }], predefined_roles: [] };
}

function event(pathname: string, user: object) {
  const eneo = {
    audit: { getConfig: vi.fn().mockResolvedValue({ id: "audit" }) },
    settings: { get: vi.fn().mockResolvedValue({ id: "settings" }) }
  };
  return {
    eneo,
    event: {
      depends: vi.fn(),
      url: new URL(`http://localhost${pathname}`),
      parent: async () => ({ user, eneo })
    } as never
  };
}

async function redirectOf(promise: Promise<unknown>) {
  try {
    await promise;
  } catch (error) {
    return error as { status: number; location: string };
  }
  return null;
}

describe("admin layout access", () => {
  it("lets an admin open every admin page with the admin settings", async () => {
    const { eneo, event: e } = event("/admin/users", userWith("admin"));
    expect(await load(e)).toEqual({ auditConfig: { id: "audit" }, settings: { id: "settings" } });
    expect(eneo.audit.getConfig).toHaveBeenCalledOnce();
  });

  it.each(["retention_manage", "retention_holds"])(
    "lets a %s role open Flow settings only, without admin-only requests",
    async (permission) => {
      const { eneo, event: allowed } = event("/admin/flow-settings", userWith(permission));
      expect(await load(allowed)).toEqual({ auditConfig: null, settings: { id: "settings" } });
      expect(eneo.audit.getConfig).not.toHaveBeenCalled();

      const tabbed = event("/admin/flow-settings?tab=retention", userWith(permission));
      expect(await load(tabbed.event)).toEqual({ auditConfig: null, settings: { id: "settings" } });

      for (const pathname of [
        "/admin",
        "/admin/users",
        "/en/admin/roles",
        "/admin/flow-settings?tab=uploads",
        "/admin/flow-settings?tab=builder"
      ]) {
        const refused = await redirectOf(load(event(pathname, userWith(permission)).event));
        expect(refused).toMatchObject({
          status: 302,
          location: "/admin/flow-settings?tab=retention"
        });
      }
    }
  );

  it("sends a user without admin or a retention permission home", async () => {
    const refused = await redirectOf(
      load(event("/admin/flow-settings", userWith("flows_manage")).event)
    );
    expect(refused).toMatchObject({ status: 302, location: "/" });
  });
});
