import { describe, expect, test, vi } from "vitest";
import { load } from "./+page.server";

describe("module login failure page", () => {
  test.each(["invalid_request", "module_unavailable", "service_unavailable"])(
    "allows the public reason %s",
    async (reason) => {
      const setHeaders = vi.fn();
      const result = await load({
        url: new URL(`https://eneo.example/module-login/failed?reason=${reason}`),
        setHeaders
      } as never);

      expect(result).toEqual({ reason });
      expect(setHeaders).toHaveBeenCalledWith(
        expect.objectContaining({
          "Cache-Control": "private, no-store, max-age=0",
          "Referrer-Policy": "no-referrer"
        })
      );
    }
  );

  test("does not reflect arbitrary reasons", async () => {
    const result = await load({
      url: new URL("https://eneo.example/module-login/failed?reason=secret-backend-detail"),
      setHeaders: vi.fn()
    } as never);

    expect(result).toEqual({ reason: "invalid_request" });
  });
});
