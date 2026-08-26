import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";

const fetchFixture = vi.hoisted(() =>
  vi.fn(
    async (
      path: string,
      request?: { params?: { query?: { folder_id?: string; folder_path?: string } } }
    ) => {
      if (path.endsWith("/preview/")) {
        return {
          fixture: true,
          scenario: "representative",
          items: [
            {
              key: "sales-site",
              name: "Sales Site",
              type: "site",
              category: "my_teams",
              url: "https://example.sharepoint.com/sites/sales"
            }
          ],
          count: 1
        };
      }
      if (path.endsWith("/tree/") && request?.params?.query?.folder_id === "policies") {
        return {
          fixture: true,
          scenario: "representative",
          items: [
            {
              id: "security-policy",
              name: "Security policy.pdf",
              type: "file",
              path: "/Policies/Security policy.pdf",
              has_children: false,
              size: 1024,
              web_url: "https://example.sharepoint.com/sites/sales/Security%20policy.pdf"
            }
          ],
          current_path: "/Policies",
          parent_id: null,
          drive_id: "sales-drive",
          site_id: "sales-site"
        };
      }
      if (path.endsWith("/tree/")) {
        return {
          fixture: true,
          scenario: "representative",
          items: [
            {
              id: "policies",
              name: "Policies",
              type: "folder",
              path: "/Policies",
              has_children: true,
              web_url: "https://example.sharepoint.com/sites/sales/Policies"
            }
          ],
          current_path: "/",
          parent_id: null,
          drive_id: "sales-drive",
          site_id: "sales-site"
        };
      }
      throw new Error(`Unexpected fixture endpoint: ${path}`);
    }
  )
);

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    client: { fetch: fetchFixture }
  })
}));

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: {
      currentSpace: {
        subscribe: (run: (space: { id: string; embedding_models: [] }) => void) => {
          run({ id: "space-1", embedding_models: [] });
          return () => undefined;
        }
      }
    },
    refreshCurrentSpace: vi.fn()
  })
}));

vi.mock("$lib/features/jobs/JobManager", () => ({
  getJobManager: () => ({
    addJob: vi.fn(),
    startFastUpdatePolling: vi.fn()
  })
}));

vi.mock("$lib/components/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() }
}));

vi.mock("$lib/core/errors", () => ({ toastError: vi.fn() }));

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, unknown>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)} ${JSON.stringify(params)}` : String(key)
    }
  )
}));

import SharePointFixtureLauncher from "./SharePointFixtureLauncher.svelte";

describe("SharePointFixtureLauncher", () => {
  it("completes a simulated import without a URL parameter or real import", async () => {
    render(SharePointFixtureLauncher, { authType: "user_oauth" });

    await page.getByRole("button", { name: "sharepoint_fixture_open" }).click();

    await expect
      .element(page.getByRole("alert"))
      .toHaveTextContent("sharepoint_fixture_compact_title");
    await vi.waitFor(() => expect(fetchFixture).toHaveBeenCalledTimes(1));
    expect(fetchFixture).toHaveBeenNthCalledWith(
      1,
      "/api/v1/integrations/sharepoint/fixtures/{scenario}/preview/",
      {
        method: "get",
        params: { path: { scenario: "representative" } }
      }
    );

    await expect.element(page.getByText("sharepoint_step_source")).toBeVisible();
    await page.getByText("Sales Site").click();
    await vi.waitFor(() => expect(fetchFixture).toHaveBeenCalledTimes(2));

    await page
      .getByRole("button", {
        name: 'sharepoint_expand_folder_named {"name":"Policies"}'
      })
      .click();
    await vi.waitFor(() => expect(fetchFixture).toHaveBeenCalledTimes(3));

    await page
      .getByRole("checkbox", {
        name: 'sharepoint_select_item {"name":"Security policy.pdf"}'
      })
      .click();
    await page.getByRole("button", { name: "continue" }).click();

    await expect.element(page.getByText("sharepoint_review_title")).toBeVisible();
    await page.getByRole("button", { name: "sharepoint_fixture_simulate_import" }).click();

    await expect
      .element(page.getByText("sharepoint_fixture_simulation_complete_title"))
      .toBeVisible();
    expect(fetchFixture).toHaveBeenCalledTimes(3);
  });
});
