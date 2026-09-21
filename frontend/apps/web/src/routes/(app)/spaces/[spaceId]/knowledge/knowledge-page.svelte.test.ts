import { page } from "@vitest/browser/context";
import { readable, writable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { beforeEach, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const bulkRun = vi.hoisted(() => vi.fn());
const refreshCurrentSpace = vi.hoisted(() => vi.fn());
const startFastUpdatePolling = vi.hoisted(() => vi.fn(async () => {}));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());
const route = vi.hoisted(() => ({
  url: new URL("http://localhost/?tab=websites"),
  state: { tab: "websites" }
}));
vi.mock("$app/state", () => ({ page: route }));
vi.mock("$app/stores", () => ({ page: readable(route) }));
vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  onNavigate: vi.fn(),
  preloadCode: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn()
}));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({ websites: { bulkRun } }) }));
vi.mock("$lib/features/jobs/JobManager", () => ({
  jobCompletionEvents: writable(null),
  getJobManager: () => ({ startFastUpdatePolling })
}));
vi.mock("$lib/components/toast", () => ({
  toast: { success: toastSuccess, error: toastError }
}));
vi.mock("$lib/core/errors", () => ({ toastError }));

const space = {
  id: "space-1",
  routeId: "space-1",
  name: "Test space",
  personal: false,
  organization: false,
  hasPermission: (_action: string, type: string) => type === "website",
  embedding_models: [{ id: "model-1", name: "Embedding model" }],
  knowledge: {
    websites: ["First", "Second", "Third"].map((name, index) => ({
      id: `website-${index}`,
      space_id: "space-1",
      name,
      url: `https://${index}.example.test`,
      update_interval: "never",
      last_indexed_at: index === 0 ? "2026-09-08T10:30:00Z" : null,
      latest_crawl: null,
      permissions: [],
      embedding_model: { id: "model-1", name: "Embedding model" }
    }))
  }
};
const currentSpace = writable(space);
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: { currentSpace, accessibleSpaces: readable([]) },
    refreshCurrentSpace
  })
}));

import KnowledgePage from "./+page.svelte";

beforeEach(() => {
  currentSpace.set(space);
  bulkRun.mockReset().mockResolvedValue({ total: 3, queued: 3, failed: 0, errors: [] });
  refreshCurrentSpace.mockReset().mockResolvedValue(undefined);
  startFastUpdatePolling.mockClear();
  toastSuccess.mockClear();
  toastError.mockClear();
});

test("syncing the selected websites refreshes jobs and reports the full selection", async () => {
  render(KnowledgePage, {
    data: {
      currentSpace: space,
      environment: {},
      settings: {},
      availableIntegrations: []
    }
  });
  await expect.element(page.getByText(/2026-09-08/)).toBeVisible();
  await page.getByRole("checkbox").first().click();
  await page.getByRole("button", { name: m.sync_selected({ count: 3 }), exact: true }).click();
  expect(bulkRun).toHaveBeenCalledWith({ website_ids: ["website-0", "website-1", "website-2"] });
  expect(toastSuccess).toHaveBeenCalledWith(m.bulk_crawl_started({ count: 3, total: 3 }));
  expect(refreshCurrentSpace).toHaveBeenCalledWith("knowledge");
  expect(startFastUpdatePolling).toHaveBeenCalledOnce();
});

test("partial bulk acceptance reports both counts and keeps the failed website selected", async () => {
  bulkRun.mockResolvedValue({
    total: 3,
    queued: 2,
    failed: 1,
    errors: [{ website_id: "website-2", error: "not_authorized" }]
  });
  render(KnowledgePage, {
    data: {
      currentSpace: space,
      environment: {},
      settings: {},
      availableIntegrations: []
    }
  });
  await page.getByRole("checkbox").first().click();
  await page.getByRole("button", { name: m.sync_selected({ count: 3 }), exact: true }).click();
  expect(toastError).toHaveBeenCalledWith(m.bulk_crawl_partial({ queued: 2, failed: 1 }));
  expect(toastSuccess).not.toHaveBeenCalled();
  expect(startFastUpdatePolling).toHaveBeenCalledOnce();
  await expect
    .element(
      page.getByRole("button", {
        name: m.sync_selected({ count: 1 }),
        exact: true
      })
    )
    .toBeVisible();
});
