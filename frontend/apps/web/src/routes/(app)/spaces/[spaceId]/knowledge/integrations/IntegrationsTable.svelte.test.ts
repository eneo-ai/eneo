import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { writable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "../../../../../../app.css";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
import type { IntegrationSyncProgress } from "$lib/features/integrations/syncProgress";

const api = vi.hoisted(() => ({
  getSyncProgress: vi.fn(),
  deleteKnowledge: vi.fn(),
  triggerFullSync: vi.fn(),
  addJob: vi.fn(),
  startFastUpdatePolling: vi.fn()
}));

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    integrations: {
      knowledge: {
        getSyncProgress: api.getSyncProgress,
        delete: api.deleteKnowledge,
        triggerFullSync: api.triggerFullSync
      }
    }
  })
}));
vi.mock("$lib/features/jobs/JobManager", () => ({
  getJobManager: () => ({
    addJob: api.addJob,
    startFastUpdatePolling: api.startFastUpdatePolling
  })
}));

function knowledge(
  id: string,
  name: string,
  fields: Partial<IntegrationKnowledge> = {},
  documents = 3,
  status = "success"
): IntegrationKnowledge {
  return {
    id,
    name,
    integration_type: "sharepoint",
    selected_item_type: "folder",
    space_id: "space-1",
    permissions: ["edit", "delete"],
    wrapper_id: null,
    wrapper_name: null,
    embedding_model: { id: "model", name: "Model" },
    ...fields,
    metadata: {
      size: 0,
      last_sync_status: status,
      last_sync_error: status === "error" ? "Graph timeout" : null,
      document_count: documents,
      last_synced_at: status === "never" ? null : "2026-10-13T08:00:00Z"
    }
  } as IntegrationKnowledge;
}

const WRAPPED = { wrapper_id: "w1", wrapper_name: "Kommunstyrelsen" };
const defaultItems = [
  knowledge("a", "Protokoll", WRAPPED, 40),
  knowledge("b", "Bilagor", WRAPPED, 2),
  knowledge("c", "HR-handboken", {}, 100, "error")
];

function spaceWith(integrationKnowledge: IntegrationKnowledge[]) {
  return {
    id: "space-1",
    routeId: "space-1",
    embedding_models: [{ id: "model" }],
    knowledge: { integrationKnowledge }
  };
}

const currentSpace = writable(spaceWith(defaultItems));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ state: { currentSpace }, refreshCurrentSpace: vi.fn() })
}));

import { pendingSyncs } from "$lib/features/integrations/pendingSyncs";
import IntegrationsTable from "./IntegrationsTable.svelte";

const SOURCE_NAMES = ["Avtal", "Blanketter", "Kommunstyrelsen", "HR-handboken"];

function sourceNames() {
  return page
    .getByRole("link")
    .elements()
    .map((link) => link.textContent?.trim())
    .filter((name) => name !== undefined && SOURCE_NAMES.includes(name));
}

function click(locator: { element: () => Element }) {
  (locator.element() as HTMLElement).click();
}

function progress(id: string): IntegrationSyncProgress {
  return {
    integration_knowledge_id: id,
    sync_type: "full",
    phase: "processing",
    started_at: "2026-10-15T10:00:00Z",
    updated_at: "2026-10-15T10:01:00Z",
    total: 20,
    done: 8,
    indexed: 7,
    unchanged: 0,
    skipped: 1,
    deleted: 0
  };
}

describe("IntegrationsTable", () => {
  beforeEach(() => {
    currentSpace.set(spaceWith(defaultItems));
    api.getSyncProgress.mockReset().mockResolvedValue({ items: [] });
    api.deleteKnowledge.mockReset().mockResolvedValue(undefined);
    api.triggerFullSync.mockReset().mockResolvedValue({ id: "job-c", status: "queued" });
    api.addJob.mockClear();
    pendingSyncs.set([]);
  });

  function liveText() {
    return [...document.querySelectorAll('[role="status"][aria-live="polite"]')]
      .map((region) => region.textContent?.trim() ?? "")
      .join(" ");
  }

  it("shows a started sync as queued until the worker reports, then announces its course", async () => {
    render(IntegrationsTable);
    await expect.element(page.getByRole("link", { name: "HR-handboken" })).toBeVisible();

    await page
      .getByRole("row")
      .filter({ hasText: "HR-handboken" })
      .getByRole("button", { name: m.actions() })
      .click();
    await page.getByRole("menuitem", { name: m.trigger_full_sync() }).click();
    await page.getByRole("button", { name: m.start_full_sync() }).click();

    await expect
      .element(page.getByText(m.integration_source_state_queued(), { exact: true }))
      .toBeVisible();
    expect(api.addJob).toHaveBeenCalledWith({ id: "job-c", status: "queued" });
    expect(api.startFastUpdatePolling).toHaveBeenCalled();
    await expect
      .poll(liveText)
      .toContain(m.integration_announce_sync_queued({ name: "HR-handboken" }));

    // A second sync is not offered while this one waits.
    await page
      .getByRole("row")
      .filter({ hasText: "HR-handboken" })
      .getByRole("button", { name: m.actions() })
      .click();
    await expect
      .element(page.getByRole("menuitem", { name: m.integration_sync_already_running() }))
      .toHaveAttribute("aria-disabled", "true");
    await page.getByRole("menuitem", { name: m.integration_sync_already_running() }).click({
      force: true
    });
    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();

    // The worker reports: the progress replaces the queued state, and its end is spoken.
    api.getSyncProgress.mockResolvedValue({ items: [progress("c")] });
    await expect
      .poll(liveText, { timeout: 5_000 })
      .toContain(m.integration_announce_sync_started({ name: "HR-handboken" }));
    expect(
      page.getByText(m.integration_source_state_queued(), { exact: true }).elements()
    ).toHaveLength(0);

    // The end is spoken once the source's row records how the sync went.
    api.getSyncProgress.mockResolvedValue({ items: [] });
    await expect
      .poll(() => api.getSyncProgress.mock.calls.length, { timeout: 5_000 })
      .toBeGreaterThan(3);
    expect(liveText()).not.toContain(
      m.integration_announce_sync_finished({ name: "HR-handboken" })
    );
    const synced = knowledge("c", "HR-handboken", {}, 100);
    currentSpace.set(
      spaceWith([
        ...defaultItems.slice(0, 2),
        { ...synced, metadata: { ...synced.metadata!, last_synced_at: "2026-10-15T10:05:00Z" } }
      ])
    );
    await expect
      .poll(liveText, { timeout: 5_000 })
      .toContain(m.integration_announce_sync_finished({ name: "HR-handboken" }));
  });

  it("keeps focus in the list when a deleted row takes its menu with it", async () => {
    api.deleteKnowledge.mockImplementation(async () => {
      currentSpace.set(spaceWith(defaultItems.filter((item) => item.id !== "c")));
    });
    render(IntegrationsTable);
    await expect.element(page.getByRole("link", { name: "HR-handboken" })).toBeVisible();

    await page
      .getByRole("row")
      .filter({ hasText: "HR-handboken" })
      .getByRole("button", { name: m.actions() })
      .click();
    await page.getByRole("menuitem", { name: m.delete() }).click();
    await page.getByRole("button", { name: m.delete() }).click();

    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
    expect(page.getByRole("link", { name: "HR-handboken" }).elements()).toHaveLength(0);
    await expect.poll(() => document.activeElement?.closest("tr") ?? null).not.toBeNull();
    expect(SOURCE_NAMES).toContain(document.activeElement?.textContent?.trim());
  });

  it("finds a source by its own name or a folder's name", async () => {
    render(IntegrationsTable);
    await expect.element(page.getByRole("link", { name: "HR-handboken" })).toBeVisible();
    await expectNoAxeViolations();

    const filter = page.getByRole("textbox", { name: m.ui_filter() }).element() as HTMLInputElement;
    filter.value = "bilag";
    filter.dispatchEvent(new Event("input", { bubbles: true }));

    await expect.poll(sourceNames).toEqual(["Kommunstyrelsen"]);
  });

  it("sorts the sources by their document count", async () => {
    render(IntegrationsTable);
    await expect.element(page.getByRole("link", { name: "HR-handboken" })).toBeVisible();

    click(page.getByRole("button", { name: m.integration_source_column_contents() }));

    // Alphabetically HR-handboken comes first; by documents (42 against 100) it comes last.
    await expect.poll(sourceNames).toEqual(["Kommunstyrelsen", "HR-handboken"]);
  });

  it("narrows the list to the sources that need attention", async () => {
    render(IntegrationsTable);
    await expect.element(page.getByRole("link", { name: "HR-handboken" })).toBeVisible();

    click(page.getByRole("button", { name: m.integration_filter_attention({ count: 1 }) }));

    await expect.poll(sourceNames).toEqual(["HR-handboken"]);
  });

  it("keeps the filter and a way back when the chosen filter no longer matches", async () => {
    render(IntegrationsTable);
    await expect.element(page.getByRole("link", { name: "HR-handboken" })).toBeVisible();
    click(page.getByRole("button", { name: m.integration_filter_attention({ count: 1 }) }));
    await expect.poll(sourceNames).toEqual(["HR-handboken"]);

    // The wrapper is deleted and the failing source recovers: one source, none failing.
    currentSpace.set(spaceWith([knowledge("c", "HR-handboken", {}, 100)]));

    await expect
      .element(page.getByRole("button", { name: m.integration_filter_show_all() }))
      .toBeVisible();
    await expect
      .element(page.getByRole("group", { name: m.integration_filter_label() }))
      .toBeVisible();
    // The live region was there before the message, so screen readers announce it.
    expect(
      [...document.querySelectorAll('[role="status"]')].map((region) => region.textContent?.trim())
    ).toContain(m.integration_filter_no_match());
    expect(
      page.getByText(m.ui_no_items_configured({ resourceNamePlural: "integration" })).elements()
    ).toHaveLength(0);
    await expectNoAxeViolations();

    click(page.getByRole("button", { name: m.integration_filter_show_all() }));
    await expect.poll(sourceNames).toEqual(["HR-handboken"]);
    // The pressed button is gone; focus lands on the filter now in use, which stays.
    await expect
      .poll(() => document.activeElement?.textContent?.trim())
      .toBe(m.integration_filter_all({ count: 1 }));
    await expect
      .element(page.getByRole("group", { name: m.integration_filter_label() }))
      .toBeVisible();
  });

  it("keeps a row's open dialog with its own source when a filter drops it", async () => {
    currentSpace.set(
      spaceWith([...defaultItems, knowledge("d", "Avtal"), knowledge("e", "Blanketter")])
    );
    render(IntegrationsTable);
    await expect.element(page.getByRole("link", { name: "Avtal" })).toBeVisible();
    click(page.getByRole("button", { name: m.integration_filter_ok({ count: 3 }) }));
    await expect.poll(sourceNames).toEqual(["Avtal", "Blanketter", "Kommunstyrelsen"]);

    await page
      .getByRole("row")
      .filter({ hasText: "Avtal" })
      .getByRole("button", { name: m.actions() })
      .click();
    await page.getByRole("menuitem", { name: m.delete() }).click();
    await expect
      .element(
        page
          .getByRole("alertdialog")
          .getByText(m.confirm_delete_integration_knowledge({ knowledgeName: "Avtal" }))
      )
      .toBeVisible();

    // Avtal fails while its dialog is open, so the filter drops it from the list.
    currentSpace.set(
      spaceWith([
        ...defaultItems,
        knowledge("d", "Avtal", {}, 3, "error"),
        knowledge("e", "Blanketter")
      ])
    );

    await expect.poll(sourceNames).toEqual(["Blanketter", "Kommunstyrelsen"]);
    // The dialog goes with its row instead of turning into Blanketter's.
    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
    expect(
      page
        .getByText(m.confirm_delete_integration_knowledge({ knowledgeName: "Blanketter" }))
        .elements()
    ).toHaveLength(0);
    expect(api.deleteKnowledge).not.toHaveBeenCalled();
  });

  it("shows a running sync's progress in the status column", async () => {
    api.getSyncProgress.mockResolvedValue({ items: [progress("c")] });
    render(IntegrationsTable);

    const bar = page.getByRole("progressbar", {
      name: m.integration_progress_label({ name: "HR-handboken" })
    });
    await expect.element(bar).toHaveAttribute("aria-valuenow", "8");
    await expect
      .element(page.getByText(m.integration_progress_syncing_of_total({ done: 8, total: 20 })))
      .toBeVisible();
    // The source failed before this sync; that stays visible while it runs.
    await expect
      .element(page.getByText(m.integration_source_state_attention(), { exact: true }))
      .toBeVisible();
    await expect.element(page.getByText(m.integration_source_updating_now())).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: m.integration_filter_syncing({ count: 1 }) }))
      .toBeVisible();
    await expectNoAxeViolations();
  });

  it("says when some folders of a source still wait for their first sync", async () => {
    currentSpace.set(spaceWith([...defaultItems, knowledge("f", "Diarium", WRAPPED, 0, "never")]));
    render(IntegrationsTable);

    await expect.element(page.getByText(m.integration_source_waiting_one())).toBeVisible();
    click(page.getByRole("button", { name: m.integration_filter_never({ count: 1 }) }));
    await expect.poll(sourceNames).toEqual(["Kommunstyrelsen"]);
  });

  it("only polls the sync progress while it is the open tab", async () => {
    const { rerender } = render(IntegrationsTable, { active: false });
    await expect.element(page.getByRole("link", { name: "HR-handboken" })).toBeVisible();
    expect(api.getSyncProgress).not.toHaveBeenCalled();

    await rerender({ active: true });
    await expect.poll(() => api.getSyncProgress.mock.calls.length).toBe(1);
  });

  it("keeps a banner only for a refused SharePoint sign-in", async () => {
    render(IntegrationsTable);
    await expect.element(page.getByRole("link", { name: "HR-handboken" })).toBeVisible();
    // A plain failure is marked by its badge alone.
    expect(page.getByText(m.integration_sources_attention_sign_in()).elements()).toHaveLength(0);

    const signInRefused = knowledge("d", "Rutiner", {}, 5, "error");
    signInRefused.metadata!.last_sync_error =
      "SharePoint credentials are invalid or expired; an administrator must reconnect the integration";
    currentSpace.set(spaceWith([...defaultItems, signInRefused]));

    await expect.element(page.getByText(m.integration_sources_attention_sign_in())).toBeVisible();
    await expect
      .element(page.getByRole("link", { name: m.integration_sources_attention_open_one() }))
      .toBeVisible();
  });
});
