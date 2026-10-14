import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import { groupIntegrationSources, sourceHref, summarizeSource } from "./sources";
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
