import type { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import type { EneoClient } from "@/lib/api/browser";
import type { Permission } from "@/lib/auth/permissions";
import { testQueryClient } from "@/test/render";
import { makeFlow } from "./flow-fixtures";
import {
  flowKeys,
  flowQueryOptions,
  flowsAvailable,
  storeFlow,
  type FlowPublic
} from "./flows-api";

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

  /** An API whose detail reads answer only when the test releases them, in the order asked. */
  function heldReads() {
    const releases: ((revision: number) => void)[] = [];
    const api = {
      GET: () =>
        new Promise((resolve) => {
          releases.push((revision) =>
            resolve({ data: makeFlow({ draft_revision: revision }), response: new Response() })
          );
        })
    } as unknown as EneoClient;
    return { api, release: (revision: number) => releases.shift()!(revision) };
  }
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
  const cachedRevision = (queryClient: QueryClient) =>
    queryClient.getQueryData<FlowPublic>(flowKeys.flow("flow-1"))?.draft_revision;

  it("keeps a stored answer when a read that began before it answers an older revision", async () => {
    const queryClient = testQueryClient();
    const { api, release } = heldReads();
    const read = queryClient.query(flowQueryOptions(api, "flow-1"));
    await settle();

    storeFlow(queryClient, makeFlow({ draft_revision: 5 }));
    release(4);
    await read.catch(() => {});
    await settle();

    expect(cachedRevision(queryClient)).toBe(5);
  });

  it("lets a newer read land after an older answer was stored", async () => {
    const queryClient = testQueryClient();
    const { api, release } = heldReads();
    queryClient.setQueryData(flowKeys.flow("flow-1"), makeFlow({ draft_revision: 6 }));
    const read = queryClient.query({ ...flowQueryOptions(api, "flow-1"), staleTime: 0 });
    await settle();

    storeFlow(queryClient, makeFlow({ draft_revision: 5 }));
    release(7);
    await read;
    await settle();

    expect(cachedRevision(queryClient)).toBe(7);
  });

  it("lets a read in flight that answers a newer revision land after a stored answer", async () => {
    const queryClient = testQueryClient();
    const { api, release } = heldReads();
    queryClient.setQueryData(flowKeys.flow("flow-1"), makeFlow({ draft_revision: 4 }));
    const read = queryClient.query({ ...flowQueryOptions(api, "flow-1"), staleTime: 0 });
    await settle();

    storeFlow(queryClient, makeFlow({ draft_revision: 5 }));
    release(7);
    // A caller awaiting the read gets an answer, not an error.
    expect((await read).draft_revision).toBe(7);
    await settle();

    expect(cachedRevision(queryClient)).toBe(7);
  });
});
