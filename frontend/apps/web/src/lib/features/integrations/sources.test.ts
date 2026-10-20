import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import {
  countSourceFilters,
  groupIntegrationSources,
  isSyncActive,
  itemState,
  itemWatchState,
  matchesSourceFilter,
  sourceHref,
  sourceKey,
  summarizeSource
} from "./sources";
import type { IntegrationSyncProgress } from "./syncProgress";

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function item(
  id: string,
  fields: Partial<IntegrationKnowledge> = {},
  metadata: Partial<Metadata> = {}
): IntegrationKnowledge {
  return {
    id,
    name: id,
    integration_type: "sharepoint",
    wrapper_id: null,
    wrapper_name: null,
    embedding_model: { id: "model" },
    ...fields,
    metadata: { size: 0, last_sync_status: "success", document_count: 1, ...metadata }
  } as IntegrationKnowledge;
}

function progress(id: string): IntegrationSyncProgress {
  return {
    integration_knowledge_id: id,
    sync_type: "full",
    phase: "processing",
    started_at: "2026-10-14T10:00:00Z",
    updated_at: "2026-10-14T10:01:00Z",
    total: null,
    done: 3,
    indexed: 3,
    unchanged: 0,
    skipped: 0,
    deleted: 0
  };
}

const CREDENTIALS =
  "SharePoint credentials are invalid or expired; an administrator must reconnect the integration";

describe("groupIntegrationSources", () => {
  it("groups SharePoint items by wrapper, whatever its size, and keeps other items alone", () => {
    const sources = groupIntegrationSources([
      item("b", { wrapper_id: "w1", wrapper_name: "Kommunstyrelsen" }),
      item("c", { wrapper_id: "w1", wrapper_name: "Kommunstyrelsen" }),
      item("d", { wrapper_id: "w2", wrapper_name: "Arkiv" }),
      item("a"),
      item("e", { integration_type: "confluence", wrapper_id: "w3" })
    ]);

    expect(sources.map((s) => [s.kind, s.id, s.name, s.items.map((i) => i.id)])).toEqual([
      ["item", "a", "a", ["a"]],
      ["wrapper", "w2", "Arkiv", ["d"]],
      ["item", "e", "e", ["e"]],
      ["wrapper", "w1", "Kommunstyrelsen", ["b", "c"]]
    ]);
  });

  it("names a wrapper after its first item when no wrapper name was stored", () => {
    const [source] = groupIntegrationSources([item("Protokoll", { wrapper_id: "w1" })]);
    expect(source.name).toBe("Protokoll");
  });
});

describe("sourceHref", () => {
  it.each([
    [{ kind: "wrapper", id: "w1" }, {}, "/spaces/s1/knowledge/integrations/wrapper/w1"],
    [{ kind: "item", id: "i1" }, {}, "/spaces/s1/knowledge/integrations/i1"],
    [
      { kind: "wrapper", id: "w1" },
      { folder: "i2", tab: "content" },
      "/spaces/s1/knowledge/integrations/wrapper/w1?folder=i2&tab=content"
    ],
    [
      { kind: "item", id: "i1" },
      { folder: null, tab: "problems" },
      "/spaces/s1/knowledge/integrations/i1?tab=problems"
    ]
  ] as const)("links %o with %o", (source, params, href) => {
    expect(sourceHref("s1", source, params)).toBe(href);
  });
});

describe("summarizeSource", () => {
  it.each([
    ["syncing beats a failure", [item("a", {}, { last_sync_status: "error" })], ["a"], "syncing"],
    [
      "any failed item needs attention",
      [item("a"), item("b", {}, { last_sync_status: "error" })],
      [],
      "attention"
    ],
    [
      "all never synced",
      [item("a", {}, { last_sync_status: "never", document_count: 0 })],
      [],
      "never"
    ],
    ["synced without documents", [item("a", {}, { document_count: 0 })], [], "empty"],
    ["synced with documents", [item("a"), item("b")], [], "ok"]
  ] as const)("%s", (_label, items, syncingIds, state) => {
    const byId = Object.fromEntries(syncingIds.map((id) => [id, progress(id)]));
    expect(summarizeSource([...items], byId).state).toBe(state);
  });

  it("adds up documents, keeps the latest sync and flags a sign-in failure", () => {
    const summary = summarizeSource(
      [
        item("a", {}, { document_count: 2, last_synced_at: "2026-10-01T10:00:00Z" }),
        item(
          "b",
          {},
          {
            document_count: 3,
            last_synced_at: "2026-10-02T10:00:00Z",
            last_sync_status: "error",
            last_sync_error: CREDENTIALS
          }
        )
      ],
      {}
    );

    expect(summary).toMatchObject({
      documentCount: 5,
      lastSyncedAt: "2026-10-02T10:00:00Z",
      credentialsFailed: true,
      progress: null
    });
    expect(summary.failedItems.map((i) => i.id)).toEqual(["b"]);
  });

  it("counts the folders still waiting for a first sync, but not one that syncs now", () => {
    const never = { last_sync_status: "never", document_count: 0 } as const;
    const summary = summarizeSource([item("a"), item("b", {}, never), item("c", {}, never)], {
      c: progress("c")
    });

    expect(summary.state).toBe("syncing");
    expect(summary.waitingItems).toBe(1);
  });

  it("does not blame the sign-in when another failure is mixed in", () => {
    const summary = summarizeSource(
      [
        item("a", {}, { last_sync_status: "error", last_sync_error: CREDENTIALS }),
        item("b", {}, { last_sync_status: "error", last_sync_error: "Graph timeout" })
      ],
      {}
    );
    expect(summary.credentialsFailed).toBe(false);
  });
});

describe("source status filters", () => {
  it("counts every filter, with a syncing source that has failed folders under both", () => {
    const failingWhileSyncing = summarizeSource(
      [item("a", {}, { last_sync_status: "error", last_sync_error: "Graph timeout" })],
      { a: progress("a") }
    );
    const counts = countSourceFilters([
      failingWhileSyncing,
      summarizeSource([item("b")], {}),
      summarizeSource([item("c", {}, { document_count: 0 })], {})
    ]);

    expect(counts).toEqual({ all: 3, attention: 1, syncing: 1, never: 0, empty: 1, ok: 1 });
    expect(matchesSourceFilter(failingWhileSyncing, "attention")).toBe(true);
  });

  it("finds a source under Waiting when only some of its folders wait for a first sync", () => {
    const partlyWaiting = summarizeSource(
      [item("a"), item("b", {}, { last_sync_status: "never", document_count: 0 })],
      {}
    );

    expect(partlyWaiting.state).toBe("ok");
    expect(matchesSourceFilter(partlyWaiting, "never")).toBe(true);
    expect(matchesSourceFilter(partlyWaiting, "ok")).toBe(true);
    expect(matchesSourceFilter(summarizeSource([item("c")], {}), "never")).toBe(false);
  });
});

describe("queued syncs", () => {
  it("reads an item as queued until its progress appears", () => {
    const queued = new Set(["a"]);

    expect(itemState(item("a"), {}, queued)).toBe("queued");
    expect(itemState(item("a"), { a: progress("a") }, queued)).toBe("syncing");
    expect(itemState(item("b"), {}, queued)).toBe("ok");
  });

  it("makes a source queued before it fails or empties, and active for the filter", () => {
    const failing = item("b", {}, { last_sync_status: "error", last_sync_error: "Graph timeout" });
    const summary = summarizeSource([item("a"), failing], {}, new Set(["a"]));

    expect(summary.state).toBe("queued");
    expect(summary.queuedItems).toBe(1);
    // The earlier failure stays countable while the new sync waits.
    expect(summary.failedItems).toEqual([failing]);
    expect(isSyncActive(summary)).toBe(true);
    expect(matchesSourceFilter(summary, "syncing")).toBe(true);
    expect(isSyncActive(summarizeSource([item("a")], {}))).toBe(false);
  });
});

describe("itemWatchState", () => {
  const now = new Date("2026-10-15T12:00:00Z").getTime();
  const expiresIn = (hours: number) => new Date(now + hours * 60 * 60 * 1000).toISOString();

  it.each([
    [expiresIn(72), "active"],
    [expiresIn(47), "expiring"],
    [expiresIn(-1), "expired"],
    [null, "none"],
    ["not a date", "none"]
  ] as const)("reads an expiry of %s as %s", (expires, state) => {
    expect(
      itemWatchState(item("a", {}, { sharepoint_subscription_expires_at: expires }), now)
    ).toBe(state);
  });
});

describe("sourceKey", () => {
  it("tells a wrapper from an item with the same id", () => {
    expect(sourceKey({ kind: "wrapper", id: "x" })).not.toBe(sourceKey({ kind: "item", id: "x" }));
  });
});
