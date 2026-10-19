// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/server", () => ({
  eneoApi: () => ({
    GET: async (path: string) => {
      if (path === "/api/v1/storage/spaces/") {
        return {
          error: { message: "Storage breakdown failed", error_id: "8bc91e0a" },
          response: new Response(null, { status: 500 })
        };
      }
      return {
        data: path === "/api/v1/token-usage/" ? { models: [] } : { total_used: 0 },
        response: new Response("{}")
      };
    }
  })
}));

import AdminUsageRoute from "./page";

describe("AdminUsageRoute", () => {
  it("keeps successful tabs hydrated when another tab's prefetch fails", async () => {
    const page = await AdminUsageRoute();
    const hydratedKeys = page.props.state.queries.map(
      (query: { queryKey: readonly unknown[] }) => query.queryKey[0]
    );

    expect(hydratedKeys).toHaveLength(2);
    expect(hydratedKeys).toEqual(expect.arrayContaining(["admin-token-usage", "admin-storage"]));
  });
});
