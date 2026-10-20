import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { writable } from "svelte/store";
import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "../../../../../../../app.css";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
import type { SyncLog } from "$lib/features/integrations/syncActivity";

const api = vi.hoisted(() => ({
  logs: {} as Record<string, SyncLog[]>,
  getSyncLogs: vi.fn()
}));

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    integrations: {
      knowledge: {
        getSyncDetails: async (args: {
          knowledge: { id: string };
          offset: number;
          limit: number;
        }) => ({
          history: await api.getSyncLogs({ ...args, skip: args.offset }),
          skipped: null
        })
      }
    }
  })
}));

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ state: { currentSpace: writable({ id: "space-1" }) } })
}));

import SourceActivityView from "./SourceActivityView.svelte";

const HOUR = 60 * 60 * 1000;

function logs(itemId: string, count: number, newest: string, fields: Partial<SyncLog> = {}) {
  return Array.from(
    { length: count },
    (_, index) =>
      ({
        id: `${itemId}-${index}`,
        integration_knowledge_id: itemId,
        sync_type: "delta",
        status: "success",
        started_at: new Date(new Date(newest).getTime() - index * HOUR).toISOString(),
        completed_at: null,
        files_processed: 1,
        files_deleted: 0,
        pages_processed: 0,
        folders_processed: 0,
        skipped_items: 0,
        skipped_details: [],
        metadata: null,
        ...fields
      }) as SyncLog
  );
}

function item(id: string, name: string): IntegrationKnowledge {
  return { id, name, folder_path: `/Shared Documents/${name}` } as IntegrationKnowledge;
}

const busy = item("busy", "Protokoll");
const quiet = item("quiet", "Kvartalsrapporter");

function show(props: Partial<Parameters<typeof render<typeof SourceActivityView>>[1]> = {}) {
  const onSelect = vi.fn();
  const view = render(SourceActivityView, {
    items: [busy, quiet],
    selectedId: null,
    signatures: { busy: "1", quiet: "1" },
    onSelect,
    ...props
  });
  return { ...view, onSelect };
}

const showOlder = () => page.getByRole("button", { name: m.integration_activity_show_older() });

describe("SourceActivityView", () => {
  beforeEach(() => {
    api.logs = {
      busy: logs("busy", 30, "2026-10-15T12:00:00Z"),
      quiet: logs("quiet", 2, "2026-06-01T09:00:00Z", {
        status: "error",
        error_message: "Quiet folder failure"
      })
    };
    // Like the endpoint: newest first, at most 100 a page.
    api.getSyncLogs.mockReset().mockImplementation(async ({ knowledge, skip, limit }) => {
      if (limit > 100) throw Object.assign(new Error("Unprocessable"), { status: 422 });
      const all = api.logs[knowledge.id] ?? [];
      return { items: all.slice(skip, skip + limit), total_count: all.length };
    });
  });

  it("reads a history longer than a page allows, page by page", async () => {
    api.logs.busy = logs("busy", 120, "2026-10-15T12:00:00Z");
    show({ items: [busy], signatures: { busy: "1" } });
    await expect
      .element(page.getByText(m.integration_activity_totals_of_all({ total: 120 })))
      .toBeVisible();
    await expect
      .element(page.getByText(m.integration_activity_files_synced_one(), { exact: true }).first())
      .toBeVisible();

    for (let page = 1; page < 12; page++) {
      await expect.element(showOlder()).toBeEnabled();
      (showOlder().element() as HTMLElement).click();
      await expect.poll(() => api.getSyncLogs.mock.calls.length).toBe(page + 1);
    }

    await expect.poll(() => showOlder().elements().length).toBe(0);
    await expect
      .element(page.getByText(m.integration_activity_totals_heading_other({ count: 120 })))
      .toBeVisible();
    expect(api.getSyncLogs.mock.calls.map(([args]) => [args.skip, args.limit])).toEqual(
      Array.from({ length: 12 }, (_, index) => [index * 10, 10])
    );
  });

  it("reaches a quiet folder's history through the folder selector", async () => {
    const { onSelect, rerender } = show();
    await expect
      .element(page.getByText(m.integration_activity_totals_heading_other({ count: 10 })))
      .toBeVisible();
    // Every folder at once stops where the busy folder's loaded history runs out.
    expect(page.getByText("Quiet folder failure").elements()).toHaveLength(0);
    await expectNoAxeViolations();

    await page
      .getByRole("combobox", { name: m.integration_source_folder() })
      .selectOptions("quiet");
    expect(onSelect).toHaveBeenCalledWith("quiet");

    await rerender({ selectedId: "quiet" });
    await expect.element(page.getByText("Quiet folder failure").first()).toBeVisible();
    await expect
      .element(page.getByText(m.integration_activity_totals_heading_other({ count: 2 })))
      .toBeVisible();
    expect(showOlder().elements()).toHaveLength(0);
    await expectNoAxeViolations();

    await page
      .getByRole("combobox", { name: m.integration_source_folder() })
      .selectOptions(m.integration_source_all_folders());
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("reloads only the folder whose sync finished, keeping what is loaded", async () => {
    const { rerender } = show();
    await expect.element(showOlder()).toBeEnabled();
    (showOlder().element() as HTMLElement).click();
    await expect
      .element(page.getByText(m.integration_activity_totals_heading_other({ count: 20 })))
      .toBeVisible();
    expect(api.getSyncLogs).toHaveBeenCalledTimes(3);

    api.logs.busy = [
      ...logs("new", 1, "2026-10-15T13:00:00Z", { files_processed: 7 }),
      ...api.logs.busy
    ];
    await rerender({ signatures: { busy: "2", quiet: "1" } });

    await expect.poll(() => api.getSyncLogs.mock.calls.length).toBe(4);
    expect(api.getSyncLogs.mock.calls[3][0]).toMatchObject({
      knowledge: { id: "busy" },
      skip: 0,
      limit: 10
    });
    await expect
      .element(page.getByText(m.integration_activity_files_synced_other({ count: 7 })))
      .toBeVisible();
    // The second page loaded before stays: 20 earlier syncs and the new one.
    await expect
      .element(page.getByText(m.integration_activity_totals_heading_other({ count: 21 })))
      .toBeVisible();
  });
});
