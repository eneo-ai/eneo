import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { readable, writable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "../../../../../../../app.css";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
import type { IntegrationSkippedDocuments } from "$lib/features/integrations/integrationDocuments";
import { groupIntegrationSources } from "$lib/features/integrations/sources";
import { OUTCOME_WAIT_MS } from "$lib/features/integrations/syncAnnouncements";
import type { IntegrationSyncProgress } from "$lib/features/integrations/syncProgress";

const api = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  listSkippedDocuments: vi.fn(),
  getSyncLogs: vi.fn(),
  getSyncProgress: vi.fn(),
  route: {
    url: new URL("http://localhost/spaces/space-1/knowledge/integrations/wrapper/w1"),
    state: {} as Record<string, unknown>
  }
}));

vi.mock("$app/state", () => ({ page: api.route }));
vi.mock("$app/stores", () => ({ page: readable(api.route) }));
vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  onNavigate: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn()
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    integrations: {
      knowledge: {
        listDocuments: api.listDocuments,
        getSyncDetails: async (args: {
          knowledge: { id: string };
          offset?: number;
          limit: number;
        }) => ({
          history:
            args.limit === 1
              ? { items: [], total_count: 0 }
              : await api.getSyncLogs({ ...args, skip: args.offset ?? 0 }),
          skipped: args.limit === 1 ? await api.listSkippedDocuments(args) : null
        }),
        getSyncProgress: api.getSyncProgress
      }
    },
    infoBlobs: { get: vi.fn() }
  })
}));
vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({ user: { hasPermission: () => false } })
}));
vi.mock("$lib/features/jobs/JobManager", () => ({
  jobCompletionEvents: writable(null),
  getJobManager: () => ({ addJob: vi.fn(), startFastUpdatePolling: vi.fn() })
}));

const CREDENTIALS =
  "SharePoint credentials are invalid or expired; an administrator must reconnect the integration";

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function knowledge(
  id: string,
  name: string,
  fields: Partial<IntegrationKnowledge> = {},
  metadata: Partial<Metadata> = {}
): IntegrationKnowledge {
  return {
    id,
    name,
    integration_type: "sharepoint",
    selected_item_type: "folder",
    folder_path: `/Shared Documents/${name}`,
    space_id: "space-1",
    permissions: ["edit", "delete"],
    url: `https://contoso.sharepoint.com/sites/ks/Shared%20Documents/${name}`,
    wrapper_id: "w1",
    wrapper_name: "Kommunstyrelsen",
    embedding_model: { id: "model" },
    ...fields,
    metadata: {
      size: 0,
      last_sync_status: "success",
      document_count: 4,
      last_synced_at: "2026-10-13T08:00:00Z",
      ...metadata
    }
  } as IntegrationKnowledge;
}

const inDays = (days: number) => new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString();

const protokoll = knowledge(
  "ik-a",
  "Protokoll",
  {},
  { sharepoint_subscription_expires_at: inDays(2.5) }
);
const skannade = knowledge(
  "ik-b",
  "Skannade",
  {},
  {
    last_sync_status: "error",
    last_sync_error: CREDENTIALS,
    document_count: 2,
    sharepoint_subscription_expires_at: inDays(-1)
  }
);

const space = {
  id: "space-1",
  routeId: "space-1",
  name: "Kommunstyrelsen",
  personal: false,
  knowledge: { integrationKnowledge: [protokoll, skannade] }
};
const currentSpace = writable(space);
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: { currentSpace },
    refreshCurrentSpace: vi.fn(async () => {})
  })
}));

import SourcePage from "./SourcePage.svelte";

function skippedList(
  entries: [string, IntegrationSkippedDocuments["items"][number]["code"], Record<string, string>?][]
): IntegrationSkippedDocuments {
  return {
    items: entries.map(([file, code, params = {}]) => ({
      file,
      reason: "",
      code,
      params,
      retry: false
    })),
    total: entries.length,
    truncated: false,
    synced_at: null
  };
}

function progressFor(id: string): IntegrationSyncProgress {
  return {
    integration_knowledge_id: id,
    sync_type: "full",
    phase: "processing",
    started_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    total: 20,
    done: 8,
    indexed: 7,
    unchanged: 0,
    skipped: 1,
    deleted: 0
  };
}

function showWrapper(search = "") {
  api.route.url = new URL(
    `http://localhost/spaces/space-1/knowledge/integrations/wrapper/w1${search}`
  );
  const [source] = groupIntegrationSources([protokoll, skannade]);
  return render(SourcePage, { source });
}

describe("source page", () => {
  beforeEach(() => {
    api.route.state = {};
    api.route.url = new URL("http://localhost/spaces/space-1/knowledge/integrations/wrapper/w1");
    api.listDocuments.mockReset().mockResolvedValue({
      items: [],
      total_count: 0,
      limit: 50,
      offset: 0,
      total_size: 0
    });
    api.getSyncLogs.mockReset().mockResolvedValue({ items: [], total_count: 0 });
    api.getSyncProgress.mockReset().mockResolvedValue({ items: [] });
    api.listSkippedDocuments.mockReset().mockImplementation(async ({ knowledge: item }) =>
      item.id === "ik-a"
        ? skippedList([
            ["scan.pdf", "no_text_layer"],
            ["bild.png", "unsupported_type", { label: "image" }]
          ])
        : skippedList([])
    );
    currentSpace.set(space);
  });

  it("opens on an overview of the folders, with the stopped sign-in called out", async () => {
    showWrapper();

    await expect
      .element(page.getByRole("heading", { level: 1 }))
      .toHaveTextContent("Kommunstyrelsen");
    const folders = page.getByRole("navigation", { name: m.integration_source_folders() });
    await expect
      .element(folders.getByRole("link", { name: m.integration_source_all_folders() }))
      .toHaveAttribute("aria-current", "page");
    await expect
      .element(
        page.getByRole("table", {
          name: m.integration_source_folders_table_label({ name: "Kommunstyrelsen" })
        })
      )
      .toBeVisible();
    await expect
      .element(page.getByText(m.integration_source_stopped_sign_in_title()))
      .toBeVisible();
    // Each folder's change notifications, in words.
    const overview = page.getByRole("table", {
      name: m.integration_source_folders_table_label({ name: "Kommunstyrelsen" })
    });
    // Folder, status, documents, last up to date, change notifications.
    const watchCell = (folder: string) =>
      overview.getByRole("row").filter({ hasText: folder }).getByRole("cell").nth(4);
    await expect.element(watchCell("Protokoll")).toHaveTextContent(m.integration_source_watch_on());
    await expect
      .element(watchCell("Skannade"))
      .toHaveTextContent(m.integration_source_watch_state_expired());
    await expect.element(page.getByText(m.integration_source_watch_expired_one())).toBeVisible();
    // A state is told by its shape as well as its colour.
    const link = (name: RegExp) => folders.getByRole("link", { name }).element();
    expect(link(/Protokoll/).querySelector("svg.lucide-check")).not.toBeNull();
    expect(link(/Skannade/).querySelector("svg.lucide-x")).not.toBeNull();
    // One blocking sign-in problem plus one scanned file; the image is skipped on purpose.
    await expect
      .element(page.getByRole("tab", { name: `${m.integration_source_tab_problems()} 2` }))
      .toBeVisible();
    await expectNoAxeViolations();
  });

  it("shows the documents of the folder the URL selects", async () => {
    showWrapper("?folder=ik-a");

    const folders = page.getByRole("navigation", { name: m.integration_source_folders() });
    await expect
      .element(folders.getByRole("link", { name: /Protokoll/ }))
      .toHaveAttribute("aria-current", "page");
    await expect.element(page.getByRole("heading", { name: "Protokoll", level: 2 })).toBeVisible();
    await expect
      .element(
        page.getByText(
          m.integration_source_watch_state_line({ state: m.integration_source_watch_on() })
        )
      )
      .toBeVisible();
    await expect.poll(() => api.listDocuments.mock.calls.at(-1)?.[0].knowledge.id).toBe("ik-a");
    await expect
      .element(
        page.getByRole("button", { name: m.integration_source_view_unreadable({ count: 2 }) })
      )
      .toBeVisible();
  });

  it("swaps the summary for live progress while a folder syncs", async () => {
    api.getSyncProgress.mockResolvedValue({ items: [progressFor("ik-a")] });
    showWrapper();

    await expect
      .element(page.getByRole("heading", { name: m.integration_progress_sync_running() }))
      .toBeVisible();
    const bar = page.getByRole("progressbar", {
      name: m.integration_progress_label({ name: "Kommunstyrelsen" })
    });
    await expect.element(bar).toHaveAttribute("aria-valuenow", "8");
    await expect.element(bar).toHaveAttribute("aria-valuemax", "20");
    await expect
      .element(page.getByText(m.integration_progress_readable({ count: 7 })))
      .toBeVisible();
    await expect.element(page.getByText("8/20")).toBeVisible();
  });

  it("keeps keyboard focus on the folder links it navigates by", async () => {
    showWrapper();
    await expect
      .element(page.getByRole("navigation", { name: m.integration_source_folders() }))
      .toBeVisible();

    // SvelteKit moves focus to the body after a navigation unless the link keeps it.
    const folderLinks = [...document.querySelectorAll("a[data-sveltekit-replacestate]")];
    // The nav's "all folders" and two folders, and the overview's two folders.
    expect(folderLinks).toHaveLength(5);
    for (const link of folderLinks) {
      expect(link.hasAttribute("data-sveltekit-keepfocus"), link.textContent ?? "").toBe(true);
    }
  });

  it("speaks a folder's sync starting and finishing in a polite live region", async () => {
    const { rerender } = showWrapper();
    await expect
      .element(page.getByRole("navigation", { name: m.integration_source_folders() }))
      .toBeVisible();
    const live = () =>
      document.querySelector('[role="status"][aria-live="polite"]')?.textContent?.trim();
    expect(live()).toBe("");

    // A changed space makes the page look for progress at once.
    api.getSyncProgress.mockResolvedValue({ items: [progressFor("ik-a")] });
    currentSpace.set({ ...space });
    await expect.poll(live).toBe(m.integration_announce_sync_started({ name: "Kommunstyrelsen" }));

    // The progress ends before the rows say how; the end is spoken once they do.
    api.getSyncProgress.mockResolvedValue({ items: [] });
    currentSpace.set({ ...space });
    await expect.poll(() => api.getSyncProgress.mock.calls.length).toBeGreaterThan(2);
    expect(live()).toBe(m.integration_announce_sync_started({ name: "Kommunstyrelsen" }));
    const synced = knowledge(
      "ik-a",
      "Protokoll",
      {},
      { last_synced_at: "2026-10-19T09:00:00Z", sharepoint_subscription_expires_at: inDays(2.5) }
    );
    await rerender({ source: groupIntegrationSources([synced, skannade])[0] });
    await expect.poll(live).toBe(m.integration_announce_sync_finished({ name: "Kommunstyrelsen" }));
  });

  it("says a sync is no longer running when its rows never tell how it ended", async () => {
    showWrapper();
    await expect
      .element(page.getByRole("navigation", { name: m.integration_source_folders() }))
      .toBeVisible();
    const live = () =>
      document.querySelector('[role="status"][aria-live="polite"]')?.textContent?.trim();

    api.getSyncProgress.mockResolvedValue({ items: [progressFor("ik-a")] });
    currentSpace.set({ ...space });
    await expect.poll(live).toBe(m.integration_announce_sync_started({ name: "Kommunstyrelsen" }));

    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    try {
      api.getSyncProgress.mockResolvedValue({ items: [] });
      currentSpace.set({ ...space });
      await vi.advanceTimersByTimeAsync(5_000);
      expect(live()).toBe(m.integration_announce_sync_started({ name: "Kommunstyrelsen" }));
      // Nothing else changes; the wait for the rows' outcome runs out.
      await vi.advanceTimersByTimeAsync(OUTCOME_WAIT_MS);
      expect(live()).toBe(m.integration_announce_sync_stopped({ name: "Kommunstyrelsen" }));
    } finally {
      vi.useRealTimers();
    }
  });

  it("puts focus on the view that replaced the one focus was in", async () => {
    const { rerender } = showWrapper("?folder=ik-a");
    await expect.element(page.getByRole("heading", { name: "Protokoll", level: 2 })).toBeVisible();

    // Back to the overview, as by the browser's back button, with focus left in the folder.
    api.route.url = new URL("http://localhost/spaces/space-1/knowledge/integrations/wrapper/w1");
    (document.activeElement as HTMLElement | null)?.blur();
    await rerender({ source: groupIntegrationSources([protokoll, skannade])[0] });
    await expect
      .poll(() => document.activeElement?.textContent?.trim())
      .toBe(m.integration_source_folders());

    // Focus that is somewhere still on the page stays there.
    const nav = page.getByRole("navigation", { name: m.integration_source_folders() });
    const folderLink = nav.getByRole("link", { name: /Skannade/ }).element() as HTMLElement;
    folderLink.focus();
    api.route.url = new URL(
      "http://localhost/spaces/space-1/knowledge/integrations/wrapper/w1?folder=ik-b"
    );
    await rerender({ source: groupIntegrationSources([protokoll, skannade])[0] });
    await expect.element(page.getByRole("heading", { name: "Skannade", level: 2 })).toBeVisible();
    expect(document.activeElement).toBe(folderLink);
  });

  it("lists the problems by cause on the problems tab", async () => {
    api.route.state = { tab: "problems" };
    showWrapper("?tab=problems");

    await expect.element(page.getByText(m.integration_problem_credentials_title())).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: m.integration_problem_copy_admin_link() }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.integration_problems_fixable_heading({ count: 1 })))
      .toBeVisible();
    await expect.element(page.getByText("scan.pdf")).toBeVisible();
    await expect
      .element(page.getByText(m.integration_problems_intentional_heading({ count: 1 })))
      .toBeVisible();
    await expectNoAxeViolations();
  });

  it("groups failures by message and shortens long file lists", async () => {
    const timeout = "Graph request failed: 504 Gateway Timeout";
    const failing = ["Vuxen", "Arkiv"].map((name, index) =>
      knowledge(`ik-f${index}`, name, {}, { last_sync_status: "error", last_sync_error: timeout })
    );
    api.listSkippedDocuments.mockImplementation(async ({ knowledge: item }) =>
      item.id === "ik-a"
        ? skippedList(
            Array.from(
              { length: 14 },
              (_, i) => [`scan-${i}.pdf`, "no_text_layer"] as [string, "no_text_layer"]
            )
          )
        : skippedList([])
    );
    api.route.state = { tab: "problems" };
    api.route.url = new URL(
      "http://localhost/spaces/space-1/knowledge/integrations/wrapper/w1?tab=problems"
    );
    render(SourcePage, { source: groupIntegrationSources([protokoll, ...failing])[0] });

    await expect
      .element(page.getByText(m.integration_problem_sync_failed_many_title({ count: 2 })))
      .toBeVisible();
    await expect
      .element(
        page.getByRole("link", {
          name: m.integration_problem_open_named_folder({ name: "/Shared Documents/Arkiv" })
        })
      )
      .toBeVisible();
    // Two folders failing the same way are one cause, the scanned files another.
    await expect
      .element(page.getByRole("tab", { name: `${m.integration_source_tab_problems()} 2` }))
      .toBeVisible();
    await expect.element(page.getByText("scan-9.pdf")).toBeVisible();
    expect(page.getByText("scan-10.pdf").elements()).toHaveLength(0);
    (
      page
        .getByRole("button", { name: m.integration_problem_show_all({ count: 14 }) })
        .element() as HTMLElement
    ).click();
    await expect.element(page.getByText("scan-13.pdf")).toBeVisible();
  });

  it("filters and collapses a long folder list and loads activity only when opened", async () => {
    const parent = knowledge("ik-p", "Arkiv", { folder_path: "/Arkiv" });
    const years = Array.from({ length: 9 }, (_, i) =>
      knowledge(`ik-y${i}`, `${2016 + i}`, { folder_path: `/Arkiv/${2016 + i}` })
    );
    render(SourcePage, { source: groupIntegrationSources([parent, ...years])[0] });

    const folders = page.getByRole("navigation", { name: m.integration_source_folders() });
    await expect.element(folders.getByRole("link", { name: /2024/ })).toBeVisible();
    // The page body has no height outside the app shell, so act on the elements directly.
    (
      folders
        .getByRole("button", { name: m.source_tree_collapse({ name: "Arkiv" }) })
        .element() as HTMLElement
    ).click();
    await expect.poll(() => folders.getByRole("link", { name: /2024/ }).elements().length).toBe(0);

    const filter = folders
      .getByRole("searchbox", { name: m.integration_source_filter_folders() })
      .element() as HTMLInputElement;
    filter.value = "2019";
    filter.dispatchEvent(new Event("input", { bubbles: true }));
    await expect.element(folders.getByRole("link", { name: /2019/ })).toBeVisible();
    expect(folders.getByRole("link", { name: /2018/ }).elements()).toHaveLength(0);

    expect(api.getSyncLogs).not.toHaveBeenCalled();
  });

  it("reloads only the folder whose sync finished, also its activity", async () => {
    api.route.state = { tab: "activity" };
    const { rerender } = showWrapper("?tab=activity");
    await expect.poll(() => api.listSkippedDocuments.mock.calls.length).toBe(2);
    await expect.poll(() => api.getSyncLogs.mock.calls.length).toBe(2);

    const synced = knowledge(
      "ik-a",
      "Protokoll",
      {},
      { last_synced_at: "2026-10-15T09:00:00Z", sharepoint_subscription_expires_at: inDays(2.5) }
    );
    await rerender({ source: groupIntegrationSources([synced, skannade])[0] });

    await expect.poll(() => api.listSkippedDocuments.mock.calls.length).toBe(3);
    await expect.poll(() => api.getSyncLogs.mock.calls.length).toBe(3);
    expect(api.listSkippedDocuments.mock.calls[2][0].knowledge.id).toBe("ik-a");
    expect(api.getSyncLogs.mock.calls[2][0].knowledge.id).toBe("ik-a");
  });

  it("shows the link and actions of a wrapper of one folder once, in the page header", async () => {
    render(SourcePage, { source: groupIntegrationSources([protokoll])[0] });

    await expect.element(page.getByRole("heading", { name: "Protokoll", level: 2 })).toBeVisible();
    expect(page.getByRole("link", { name: m.open_in_sharepoint() }).elements()).toHaveLength(1);
    expect(page.getByRole("button", { name: m.actions() }).elements()).toHaveLength(1);
  });

  it("shows a source of one folder without a folder list", async () => {
    const alone = knowledge("ik-c", "Rutiner", { wrapper_id: null, wrapper_name: null });
    api.route.url = new URL("http://localhost/spaces/space-1/knowledge/integrations/ik-c");
    render(SourcePage, { source: groupIntegrationSources([alone])[0] });

    await expect.poll(() => api.listDocuments.mock.calls.at(-1)?.[0].knowledge.id).toBe("ik-c");
    expect(
      page.getByRole("navigation", { name: m.integration_source_folders() }).elements()
    ).toHaveLength(0);
    await expect
      .element(page.getByRole("link", { name: m.open_in_sharepoint() }).first())
      .toHaveAttribute("href", alone.url as string);
  });
});
