import { describe, expect, it, vi } from "vitest";

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

  it.each(["flows_manage", "retention_manage", "retention_holds"])(
    "sends a user with %s but without admin home",
    async (permission) => {
      const refused = await redirectOf(load(event("/admin", userWith(permission)).event));
      expect(refused).toMatchObject({ status: 302, location: "/" });
    }
  );
});
