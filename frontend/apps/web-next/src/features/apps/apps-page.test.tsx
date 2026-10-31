// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import {
  spaceHasPermission,
  type ResourcePermission,
  type Space,
  type SpaceResource
} from "@/features/spaces/space";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { AppsPage } from "./apps-page";

const state = vi.hoisted(() => ({ space: null as unknown }));

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    space: state.space,
    routeId: "space-1",
    can: (action: ResourcePermission, resource: SpaceResource) =>
      spaceHasPermission(state.space as Space, action, resource)
  })
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: {} }));

afterEach(cleanup);

const apps = (count: number) =>
  Array.from({ length: count }, (_, index) => ({
    id: `app-${index}`,
    name: `App ${index + 1}`,
    description: null,
    published: true,
    permissions: ["read"],
    updated_at: "2026-09-10T08:00:00Z"
  }));

function show(count: number) {
  state.space = makeSpace({ apps: apps(count) });
  return renderInApp(<AppsPage />);
}

describe("AppsPage filter", () => {
  it("is left out on a phone while there are few apps, and comes with many", () => {
    setViewport("phone");
    show(3);
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.queryByRole("textbox", { name: /Filtrera/ })).toBeNull();
    cleanup();
    show(7);
    expect(screen.getByRole("textbox", { name: /Filtrera/ })).toBeTruthy();
  });

  it("is always there from a tablet up", () => {
    setViewport("tablet-portrait");
    show(3);
    expect(screen.getByRole("textbox", { name: /Filtrera/ })).toBeTruthy();
  });
});
