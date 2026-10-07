import { page } from "vitest/browser";
import { mount, unmount } from "svelte";
import { createEneo, type FlowSparse } from "@eneo/eneo-js";
import { expect, it, vi } from "vitest";
import { withLocale } from "$lib/features/flows/testLocale";
import { load } from "./+page";
import Harness from "./FlowListRefreshHarness.svelte";

vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({ user: { id: "user-1", hasPermission: () => false } })
}));
vi.mock("$lib/features/spaces/SpacesManager", async () => {
  const { writable } = await import("svelte/store");
  const currentSpace = writable({ routeId: "space-1", members: [] });
  return { getSpacesManager: () => ({ state: { currentSpace } }) };
});
vi.mock("$app/paths", () => ({ base: "", assets: "", resolve: (path: string) => path }));

const existing: FlowSparse = {
  id: "existing",
  name: "Existing flow",
  space_id: "space-1",
  space_name: "Test space",
  tenant_id: "tenant-1",
  step_count: 0,
  run_history_retention: {
    state: "off",
    contributors: { flow: null, organization: null, space: null }
  }
};
const newest = { ...existing, id: "newest", name: "Newest flow" };
it.each(["sv", "en"] as const)(
  "loads all pages and preserves completed creation: %s",
  async (locale) => {
    const restore = withLocale(locale);
    let failReads = false;
    let nonProgress = false;
    try {
      const eneo = createEneo({
        baseUrl: "https://test-only.invalid",
        fetch: async (input, init) => {
          const request = new Request(input, init);
          if (request.method === "POST") return Response.json({ ...newest, steps: [] });
          if (failReads)
            return Response.json(
              { message: "test-only-private-diagnostic", eneo_error_code: 9024 },
              { status: 502 }
            );
          const url = new URL(request.url);
          const later = Number(url.searchParams.get("offset")) === 1;
          return Response.json({
            items: nonProgress ? [] : later ? [newest] : [existing],
            count: nonProgress ? 0 : 1,
            has_more: nonProgress || !later
          });
        }
      });
      const data = await load({
        parent: async () => ({
          eneo,
          currentSpace: { id: "space-1" },
          user: { roles: [{ id: "viewer", name: "Viewer", permissions: ["flows_view"] }] }
        })
      });
      expect(data.flows.map((flow) => flow.id)).toEqual([existing.id, newest.id]);
      const component = mount(Harness, {
        target: document.body,
        props: { eneo, initial: [existing] }
      });
      try {
        const { manager } = component;
        const alert = page.getByRole("alert");
        const retry = page.getByRole("button", { name: locale === "sv" ? "Försök igen" : "Retry" });
        failReads = true;
        expect((await manager.createFlow("Newest flow")).id).toBe(newest.id);
        await expect.element(alert).toBeVisible();
        await expect.element(page.getByText("Existing flow", { exact: true })).toBeVisible();
        failReads = false;
        await retry.click();
        await expect.element(page.getByText("Newest flow", { exact: true })).toBeVisible();
        await expect.element(alert).not.toBeInTheDocument();
        nonProgress = true;
        await manager.refreshFlows();
        await expect.element(alert).toBeVisible();
      } finally {
        await unmount(component);
      }
    } finally {
      restore();
    }
  }
);
