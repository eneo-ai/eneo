import { EneoError } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function event(list: () => Promise<unknown>, security: () => Promise<unknown>) {
  return {
    parent: async () => ({
      eneo: { spaces: { admin: { list } }, securityClassifications: { list: security } }
    }),
    depends: vi.fn()
  };
}

const list = { items: [], widget_requests: [] };

describe("loading Admin → Ytor", () => {
  test("returns the whole list and whether classifications are in use", async () => {
    const loadEvent = event(
      async () => list,
      async () => ({ security_enabled: true, security_classifications: [] })
    );
    await expect(load(loadEvent as never)).resolves.toEqual({ list, securityEnabled: true });
    expect(loadEvent.depends).toHaveBeenCalledWith("admin:spaces");
  });

  test("a refusal becomes the forbidden page", async () => {
    const refused = event(
      () => Promise.reject(new EneoError("Forbidden", "RESPONSE", 403, 0, {})),
      async () => null
    );
    await expect(load(refused as never)).rejects.toMatchObject({ status: 403 });
  });

  test("any other failure is left to the page, which offers another try", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const failed = event(
      () => Promise.reject(new EneoError("Down", "SERVER", 502, 0, {})),
      async () => null
    );
    await expect(load(failed as never)).resolves.toEqual({ list: null, securityEnabled: false });
  });

  test("the list still loads when the classification setting cannot be read", async () => {
    const partly = event(
      async () => list,
      () => Promise.reject(new Error("offline"))
    );
    await expect(load(partly as never)).resolves.toEqual({ list, securityEnabled: false });
  });
});
