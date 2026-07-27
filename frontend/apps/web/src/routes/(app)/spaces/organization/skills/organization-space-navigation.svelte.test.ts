import type { ResourcePermission } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

vi.mock("$app/stores", async () => {
  const { readable } = await import("svelte/store");
  return {
    page: readable({ url: new URL("https://example.test/spaces/organization/skills") })
  };
});

vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    environment: { helpCenterUrl: "" },
    featureFlags: { showHelpCenter: false },
    versions: { frontend: "test", backend: "test", client: "test" }
  })
}));

import SpaceMenu, { type SpaceMenuContext } from "../../[spaceId]/SpaceMenu.svelte";

function organizationContext(
  canAccess: (
    action: ResourcePermission,
    resource: Parameters<SpaceMenuContext["hasPermission"]>[1]
  ) => boolean
): SpaceMenuContext {
  return {
    routeId: "organization",
    personal: false,
    organization: true,
    hasPermission: canAccess
  };
}

describe("organisation Skills navigation", () => {
  test("uses the canonical organisation space menu for administrators", async () => {
    render(SpaceMenu, {
      space: organizationContext((_action, resource) =>
        ["website", "skill", "space"].includes(resource)
      )
    });

    await expect.element(page.getByRole("link", { name: m.knowledge() })).toBeVisible();
    await expect
      .element(page.getByRole("link", { name: m.skills() }))
      .toHaveAttribute("aria-current", "page");
    await expect.element(page.getByRole("link", { name: m.settings() })).toBeVisible();
  });

  test("does not show organisation destinations without administrator access", async () => {
    render(SpaceMenu, {
      space: organizationContext(() => false)
    });

    await expect.element(page.getByRole("link", { name: m.skills() })).not.toBeInTheDocument();
    await expect.element(page.getByRole("link", { name: m.knowledge() })).not.toBeInTheDocument();
    await expect.element(page.getByRole("link", { name: m.settings() })).not.toBeInTheDocument();
  });
});
