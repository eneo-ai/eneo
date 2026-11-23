import { describe, expect, it } from "vitest";
import type { Permission } from "@/lib/auth/permissions";
import { testQueryClient } from "@/test/render";
import { makeFlow } from "./flow-fixtures";
import { flowKeys, flowsAvailable, storeFlow } from "./flows-api";

const userWith = (permissions: Permission[]) => ({
  roles: [{ permissions }],
  predefined_roles: []
});

describe("flowsAvailable", () => {
  it("shows flows when the tenant has them and the user may see flows", () => {
    expect(flowsAvailable({ flows_enabled: true }, userWith(["flows_view"]))).toBe(true);
  });

  it("hides flows from a tenant that has them switched off", () => {
    expect(flowsAvailable({ flows_enabled: false }, userWith(["flows_view"]))).toBe(false);
  });

  it("hides flows when the settings do not say (an older backend)", () => {
    expect(flowsAvailable({}, userWith(["flows_view"]))).toBe(false);
  });

  it("hides flows from a user without the permission to see them", () => {
    // Tracing alone does not include seeing flows (the backend's aliases).
    expect(flowsAvailable({ flows_enabled: true }, userWith(["flows_trace"]))).toBe(false);
    expect(flowsAvailable({ flows_enabled: true }, userWith(["apps"]))).toBe(false);
  });

  it.each<Permission>(["flows_run", "flows_manage", "flows"])(
    "shows flows to a role holding only %s, which includes seeing them",
    (permission) => {
      expect(flowsAvailable({ flows_enabled: true }, userWith([permission]))).toBe(true);
    }
  );
});

describe("storeFlow", () => {
  it("leaves a newer cached draft as it was, still invalidated, when an older answer arrives", async () => {
    const queryClient = testQueryClient();
    const key = flowKeys.flow("flow-1");
    queryClient.setQueryData(key, makeFlow({ draft_revision: 6 }), { updatedAt: 1000 });
    await queryClient.invalidateQueries({ queryKey: key, refetchType: "none" });
    queryClient.setQueryData(flowKeys.list("space-1"), []);

    storeFlow(queryClient, makeFlow({ draft_revision: 5 }));

    const after = queryClient.getQueryState(key)!;
    expect(queryClient.getQueryData<{ draft_revision: number }>(key)?.draft_revision).toBe(6);
    expect(after.isInvalidated).toBe(true);
    expect(after.dataUpdatedAt).toBe(1000);
    // The space's list is still marked stale.
    expect(queryClient.getQueryState(flowKeys.list("space-1"))?.isInvalidated).toBe(true);
  });
});
