import type { ResourcePermission } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const viewer = vi.hoisted(() => ({ flowsView: true }));

vi.mock("$app/stores", async () => {
  const { readable } = await import("svelte/store");
  return {
    page: readable({ url: new URL("https://example.test/spaces/space-1/overview") })
  };
});

vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    environment: { helpCenterUrl: "", newAppUrl: "https://next.example.test/" },
    featureFlags: { showHelpCenter: false },
    versions: { frontend: "test", backend: "test", client: "test" },
    user: { hasPermission: (permission: string) => permission === "flows_view" && viewer.flowsView }
  })
}));

import SpaceMenu, { type SpaceMenuContext } from "./SpaceMenu.svelte";

/** A shared space whose apps the user may not read. */
const withoutApps: SpaceMenuContext = {
  routeId: "space-1",
  personal: false,
  organization: false,
  hasPermission: (_action: ResourcePermission, resource) => resource !== "app"
};

describe("the space menu's Flows link", () => {
  test("follows the flows permission, not the apps", async () => {
    viewer.flowsView = true;
    render(SpaceMenu, { space: withoutApps });

    await expect
      .element(page.getByRole("link", { name: m.flows() }))
      .toHaveAttribute("href", "https://next.example.test/spaces/space-1/flows");
    await expect.element(page.getByRole("link", { name: m.apps() })).not.toBeInTheDocument();
  });

  test("is left out without the flows permission", async () => {
    viewer.flowsView = false;
    render(SpaceMenu, { space: withoutApps });

    await expect.element(page.getByRole("link", { name: m.overview() })).toBeVisible();
    await expect.element(page.getByRole("link", { name: m.flows() })).not.toBeInTheDocument();
  });
});
