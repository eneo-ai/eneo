import { EneoError } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function event(get: (args: { id: string }) => Promise<unknown>) {
  return {
    parent: async () => ({
      eneo: {
        spaces: { admin: { get } },
        securityClassifications: { list: async () => ({ security_enabled: true }) }
      }
    }),
    depends: vi.fn(),
    params: { spaceId: "space-1" }
  };
}

describe("loading a space in Admin → Ytor", () => {
  test("loads the space the URL names", async () => {
    const get = vi.fn(async () => ({ id: "space-1" }));
    const loadEvent = event(get);
    await expect(load(loadEvent as never)).resolves.toEqual({
      space: { id: "space-1" },
      securityEnabled: true
    });
    expect(get).toHaveBeenCalledWith({ id: "space-1" });
    expect(loadEvent.depends).toHaveBeenCalledWith("admin:space");
  });

  test("a space that is not shown here renders the page's own not-found state", async () => {
    const missing = event(() => Promise.reject(new EneoError("Not found", "RESPONSE", 404, 0, {})));
    await expect(load(missing as never)).resolves.toEqual({ space: null, securityEnabled: true });
  });

  test("a refusal becomes the forbidden page, and other failures the error page", async () => {
    const refused = event(() => Promise.reject(new EneoError("Forbidden", "RESPONSE", 403, 0, {})));
    await expect(load(refused as never)).rejects.toMatchObject({ status: 403 });
    const failed = event(() => Promise.reject(new EneoError("Down", "SERVER", 502, 0, {})));
    await expect(load(failed as never)).rejects.toMatchObject({ status: 502 });
  });
});
