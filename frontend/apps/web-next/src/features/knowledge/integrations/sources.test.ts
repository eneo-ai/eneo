import type { IntegrationKnowledge } from "../knowledge";
import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";
import sv from "@/lib/i18n/messages/sv.json";
import {
  countSourceFilters,
  findWrapperSource,
  groupIntegrationSources,
  groupSourcesBySpace,
  matchesSourceFilter,
  sourceContentsLabel,
  sourceHref,
  sourceTabParam,
  summarizeSource
} from "./sources";
import type { IntegrationSyncProgress } from "./sync-progress";

const t = createTranslator({ locale: "sv", messages: sv as Record<string, string> });
const swedish = new Intl.Collator("sv").compare;

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
    const sources = groupIntegrationSources(
      [
        item("b", { wrapper_id: "w1", wrapper_name: "Kommunstyrelsen" }),
        item("c", { wrapper_id: "w1", wrapper_name: "Kommunstyrelsen" }),
        item("d", { wrapper_id: "w2", wrapper_name: "Arkiv" }),
        item("a"),
        item("e", { integration_type: "confluence", wrapper_id: "w3" })
      ],
      swedish
    );

    expect(sources.map((s) => [s.kind, s.id, s.name, s.items.map((i) => i.id)])).toEqual([
      ["item", "a", "a", ["a"]],
      ["wrapper", "w2", "Arkiv", ["d"]],
      ["item", "e", "e", ["e"]],
      ["wrapper", "w1", "Kommunstyrelsen", ["b", "c"]]
    ]);
  });

  it("names a wrapper after its first item when no wrapper name was stored", () => {
    const [source] = groupIntegrationSources([item("Protokoll", { wrapper_id: "w1" })], swedish);
    expect(source?.name).toBe("Protokoll");
  });

  it("sorts by name with the locale's collator, not the runtime's default", () => {
    const items = [item("Äldreomsorg"), item("Vuxen"), item("Arkiv")];
    expect(groupIntegrationSources(items, swedish).map((s) => s.name)).toEqual([
      "Arkiv",
      "Vuxen",
      "Äldreomsorg"
    ]);
    expect(
      groupIntegrationSources(items, new Intl.Collator("en").compare).map((s) => s.name)
    ).toEqual(["Äldreomsorg", "Arkiv", "Vuxen"]);
  });
});

describe("findWrapperSource", () => {
  it("is the wrapper's SharePoint items as one source, or nothing for an unknown wrapper", () => {
    const items = [
      item("b", { wrapper_id: "w1", wrapper_name: "Kommunstyrelsen" }),
      item("c", { wrapper_id: "w1", wrapper_name: "Kommunstyrelsen" }),
      item("d", { integration_type: "confluence", wrapper_id: "w2" })
    ];
    const source = findWrapperSource(items, "w1");
    expect([source?.kind, source?.name, source?.items.map((i) => i.id)]).toEqual([
      "wrapper",
      "Kommunstyrelsen",
      ["b", "c"]
    ]);
    // Only SharePoint imports group by wrapper.
    expect(findWrapperSource(items, "w2")).toBeUndefined();
    expect(findWrapperSource(items, "w9")).toBeUndefined();
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
});

describe("groupSourcesBySpace", () => {
  it("groups each space's items into its own sources", () => {
    const spaceA = { id: "s1", name: "Socialtjänsten" };
    const spaceB = { id: "s2", name: "Stadsbyggnad" };
    const grouped = groupSourcesBySpace(
      [
        { space: spaceA, knowledge: item("a", { wrapper_id: "w1", wrapper_name: "KS" }) },
        { space: spaceB, knowledge: item("b") },
        { space: spaceA, knowledge: item("c", { wrapper_id: "w1", wrapper_name: "KS" }) }
      ],
      swedish
    );

    expect(grouped.map(({ space, source }) => [space.id, source.id, source.items.length])).toEqual([
      ["s1", "w1", 2],
      ["s2", "b", 1]
    ]);
  });
});

describe("sourceContentsLabel", () => {
  it("names sites, folders and files, and falls back to the item count", () => {
    expect(
      sourceContentsLabel(
        [
          item("a", { selected_item_type: "site_root" }),
          item("b", { selected_item_type: "folder" }),
          item("c", { selected_item_type: "folder" }),
          item("d", { selected_item_type: "file" })
        ],
        t
      )
    ).toBe(
      [
        t("sharepoint_wrapper_sites_one", { count: 1 }),
        t("sharepoint_wrapper_folders_other", { count: 2 }),
        t("sharepoint_wrapper_files_one", { count: 1 })
      ].join(", ")
    );
    expect(sourceContentsLabel([item("a", { selected_item_type: "page" })], t)).toBe(
      t("wrapper_items_count_one", { count: 1 })
    );
  });
});

describe("sourceTabParam", () => {
  it.each([
    ["problems", "problems"],
    ["skipped", "problems"],
    ["activity", "activity"],
    ["content", "content"],
    ["documents", undefined],
    [undefined, undefined],
    [["problems", "activity"], undefined]
  ] as const)("%o → %s", (value, tab) => {
    expect(sourceTabParam(value as string | string[] | undefined)).toBe(tab);
  });
});
