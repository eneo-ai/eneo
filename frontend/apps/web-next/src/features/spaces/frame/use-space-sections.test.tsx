// @vitest-environment jsdom
import { cleanup, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHookInApp, testAppContext } from "@/test/render";
import {
  spaceHasPermission,
  type ResourcePermission,
  type Space,
  type SpaceResource
} from "../space";
import { makeSpace } from "../testing/space-fixture";

const state = vi.hoisted(() => ({ space: null as unknown }));
const api = vi.hoisted(() => ({
  GET: vi.fn(() =>
    Promise.resolve({ data: { items: [{ id: "f1" }] }, response: new Response("{}") })
  )
}));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("../use-space", () => ({
  useSpace: () => ({
    space: state.space,
    routeId: "space-1",
    can: (action: ResourcePermission, resource: SpaceResource) =>
      spaceHasPermission(state.space as Space, action, resource)
  })
}));

import { useSpaceSections } from "./use-space-sections";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/** A space whose apps the user may not read. */
function spaceWithoutApps(overrides: Record<string, unknown> = {}) {
  const space = makeSpace({ overrides });
  space.applications!.apps.permissions = [];
  return space;
}

function sections(space: Space, flows: boolean) {
  state.space = space;
  return renderHookInApp(() => useSpaceSections(), {
    appContext: testAppContext({ featureFlags: { federation: false, flows } })
  });
}

describe("useSpaceSections", () => {
  it("lists the flows for their count without the apps", async () => {
    const { result } = sections(spaceWithoutApps(), true);
    await waitFor(() =>
      expect(result.current.find((section) => section.id === "flows")?.count).toBe(1)
    );
    expect(api.GET).toHaveBeenCalledWith("/api/v1/flows/", expect.anything());
  });

  it("reads no flows where the tenant has none for the user, or in the organisation space", () => {
    sections(spaceWithoutApps(), false);
    expect(api.GET).not.toHaveBeenCalled();
    cleanup();
    sections(spaceWithoutApps({ organization: true }), true);
    expect(api.GET).not.toHaveBeenCalled();
  });
});
