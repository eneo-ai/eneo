import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

type FixtureScenario = "representative" | "large_tenant" | "empty";

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

const fetchFixture = vi.hoisted(() =>
  vi.fn(
    async (
      path: string,
      request?: {
        params?: {
          path?: { scenario?: FixtureScenario };
          query?: { folder_id?: string; folder_path?: string };
        };
      }
    ) => {
      const scenario = request?.params?.path?.scenario ?? "representative";
      const site =
        scenario === "large_tenant"
          ? {
              key: "large-site",
              name: "Large Tenant Site",
              type: "site",
              category: "my_teams",
              url: "https://example.sharepoint.com/sites/large"
            }
          : {
              key: "sales-site",
              name: "Sales Site",
              type: "site",
              category: "my_teams",
              url: "https://example.sharepoint.com/sites/sales"
            };

      if (path.endsWith("/preview/")) {
        return {
          fixture: true,
          scenario,
          items: scenario === "empty" ? [] : [site],
          count: scenario === "empty" ? 0 : 1
        };
      }
      if (path.endsWith("/tree/") && request?.params?.query?.folder_id === "policies") {
        return {
          fixture: true,
          scenario,
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
          site_id: site.key
        };
      }
      if (path.endsWith("/tree/")) {
        return {
          fixture: true,
          scenario,
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
          site_id: site.key
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
  beforeEach(() => {
    fetchFixture.mockClear();
  });

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

    await page.getByRole("button", { name: "close" }).first().click();
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();

    await page.getByRole("button", { name: "sharepoint_fixture_open" }).click();

    await expect.element(page.getByText("sharepoint_step_source")).toBeVisible();
    await expect
      .element(page.getByText("sharepoint_fixture_simulation_complete_title"))
      .not.toBeInTheDocument();
    await expect.element(page.getByText("Sales Site")).toBeVisible();
    expect(fetchFixture).toHaveBeenCalledTimes(3);
  });

  it("locks scenario changes while a preview is loading", async () => {
    const representativePreview = {
      fixture: true as const,
      scenario: "representative" as const,
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
    const pendingPreview = createDeferred<typeof representativePreview>();
    fetchFixture.mockImplementationOnce(() => pendingPreview.promise);

    render(SharePointFixtureLauncher, { authType: "user_oauth" });
    await page.getByRole("button", { name: "sharepoint_fixture_open" }).click();
    await vi.waitFor(() => expect(fetchFixture).toHaveBeenCalledTimes(1));

    const scenarioSelector = page.getByRole("button", {
      name: "sharepoint_fixture_scenario_label"
    });
    await expect.element(scenarioSelector).toBeDisabled();

    (scenarioSelector.element() as HTMLButtonElement).click();
    expect(fetchFixture).toHaveBeenCalledTimes(1);
    await expect
      .element(page.getByRole("option", { name: "sharepoint_fixture_scenario_large_tenant" }))
      .not.toBeInTheDocument();

    pendingPreview.resolve(representativePreview);
    await expect.element(scenarioSelector).not.toBeDisabled();
    await expect.element(page.getByText("Sales Site")).toBeVisible();

    await scenarioSelector.click();
    await page.getByRole("option", { name: "sharepoint_fixture_scenario_large_tenant" }).click();

    await vi.waitFor(() => expect(fetchFixture).toHaveBeenCalledTimes(2));
    await expect.element(page.getByText("Large Tenant Site")).toBeVisible();
    await page.getByText("Large Tenant Site").click();
    await vi.waitFor(() => expect(fetchFixture).toHaveBeenCalledTimes(3));

    expect(fetchFixture).toHaveBeenNthCalledWith(
      3,
      "/api/v1/integrations/sharepoint/fixtures/{scenario}/tree/",
      {
        method: "get",
        params: {
          path: { scenario: "large_tenant" },
          query: {
            site_id: "large-site",
            drive_id: undefined,
            folder_id: undefined,
            folder_path: undefined
          }
        }
      }
    );
  });
});
