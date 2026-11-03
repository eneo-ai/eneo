import { describe, expect, it } from "vitest";
import type { Website } from "@/features/knowledge/knowledge";
import { makeAssistant, makeCollection, makeSpace, makeWebsite } from "../testing/space-fixture";
import { overviewKnowledgeRows, recentChatItems, uploadTargets } from "./overview-data";

const compare = new Intl.Collator("sv").compare;

const crawl = (overrides: Record<string, unknown>) =>
  makeWebsite({
    latest_crawl: {
      ...(makeWebsite().latest_crawl as Record<string, unknown>),
      ...overrides
    }
  }) as unknown as Website;

describe("overviewKnowledgeRows", () => {
  it("merges the space's own sources, newest first, with content and status", () => {
    const space = makeSpace({
      collections: [
        makeCollection({ updated_at: "2026-09-01T08:00:00Z" }),
        makeCollection({ id: "empty", name: "Tom", metadata: { num_info_blobs: 0, size: 0 } }),
        makeCollection({ id: "shared", space_id: "other-space" })
      ],
      websites: [crawl({ status: "failed", finished_at: "2026-09-24T10:00:00Z" })],
      integrations: [
        {
          id: "i1",
          name: "Avtal",
          space_id: "space-1",
          integration_type: "confluence",
          embedding_model: { id: "embed-1" },
          metadata: { size: 0, last_synced_at: null }
        }
      ]
    });

    const rows = overviewKnowledgeRows(space, "space-1", compare);
    expect(rows.map((row) => row.key)).toEqual([
      "website-website-1",
      "collection-empty",
      "collection-collection-1",
      "integration-i1"
    ]);
    const [website, empty, collection, integration] = rows;
    expect(website).toMatchObject({
      kind: "website",
      name: "www.upphandlingsmyndigheten.se",
      href: "/spaces/space-1/knowledge/websites/website-1",
      content: { key: "space_pages_count", values: { count: 318 } },
      status: { tone: "error", fixHref: "/spaces/space-1/knowledge/websites/website-1" }
    });
    expect(empty?.status).toEqual({ tone: "neutral", labelKey: "empty" });
    expect(collection).toMatchObject({
      href: "/spaces/space-1/knowledge/collections/collection-1",
      content: { key: "space_files_count", values: { count: 42 } },
      status: { tone: "success", labelKey: "space_status_indexed" }
    });
    expect(integration).toMatchObject({
      kind: "integration",
      href: "/spaces/space-1/knowledge/integrations/i1",
      content: { key: "space_documents_count", values: { count: 0 } },
      updatedAt: null,
      status: { tone: "neutral", labelKey: "integration_source_state_never" }
    });
  });
});

describe("recentChatItems", () => {
  it("puts the most recently changed first", () => {
    const older = makeAssistant({ id: "older", updated_at: "2026-01-01T00:00:00Z" });
    const newer = makeAssistant({ id: "newer", name: "B", updated_at: "2026-09-01T00:00:00Z" });
    const group = {
      id: "group",
      type: "group-chat",
      name: "Grupp",
      published: false,
      user_id: "u",
      metadata_json: null,
      created_at: "2026-05-01T00:00:00Z",
      updated_at: "2026-05-01T00:00:00Z"
    };
    const space = makeSpace({ assistants: [older, newer], groupChats: [group] });

    expect(recentChatItems(space, compare).map((item) => item.id)).toEqual([
      "newer",
      "group",
      "older"
    ]);
  });
});

describe("uploadTargets", () => {
  it("offers own, editable collections whose embedding model the space still has", () => {
    const space = makeSpace({
      collections: [
        makeCollection({ id: "b", name: "B" }),
        makeCollection({ id: "a", name: "A" }),
        makeCollection({ id: "readonly", permissions: ["read"] }),
        makeCollection({ id: "shared", space_id: "org" }),
        makeCollection({ id: "old-model", embedding_model: { id: "removed" } })
      ]
    });
    expect(uploadTargets(space, compare).map((collection) => collection.id)).toEqual(["a", "b"]);
  });

  it("orders names the Swedish way when given a Swedish collator", () => {
    const space = makeSpace({
      collections: [
        makeCollection({ id: "ä", name: "Ärenden" }),
        makeCollection({ id: "z", name: "Zeta" }),
        makeCollection({ id: "a", name: "Avtal" })
      ]
    });
    expect(uploadTargets(space, compare).map((collection) => collection.name)).toEqual([
      "Avtal",
      "Zeta",
      "Ärenden"
    ]);
  });
});
