import { describe, expect, it } from "vitest";
import type { Website } from "@/features/knowledge/knowledge";
import { makeAssistant, makeCollection, makeSpace, makeWebsite } from "../testing/space-fixture";
import { websiteStatus } from "@/features/knowledge/website-status";
import { assistantModelName } from "../space-models";
import {
  defaultModelFirst,
  overviewKnowledgeRows,
  recentChatItems,
  uploadTargets
} from "./overview-data";

const compare = new Intl.Collator("sv").compare;

const crawl = (overrides: Record<string, unknown>) =>
  makeWebsite({
    latest_crawl: {
      ...(makeWebsite().latest_crawl as Record<string, unknown>),
      ...overrides
    }
  }) as unknown as Website;

describe("websiteStatus", () => {
  const href = "/spaces/s/knowledge/websites/w";

  it("maps every crawl state to a tone and label", () => {
    expect(websiteStatus(makeWebsite({ latest_crawl: null }) as unknown as Website, href)).toEqual({
      tone: "neutral",
      labelKey: "website_not_yet_crawled"
    });
    expect(websiteStatus(crawl({ status: "queued" }), href)).toEqual({
      tone: "accent",
      labelKey: "queued"
    });
    expect(websiteStatus(crawl({ status: "in progress" }), href)).toEqual({
      tone: "accent",
      labelKey: "space_status_syncing",
      isPulsing: true
    });
    expect(websiteStatus(crawl({}), href)).toEqual({
      tone: "success",
      labelKey: "space_status_indexed"
    });
    expect(websiteStatus(crawl({ pages_failed: 3 }), href)).toEqual({
      tone: "warning",
      labelKey: "synced_with_warnings"
    });
  });

  it("links a failed crawl to the website page, where it can be run again", () => {
    expect(websiteStatus(crawl({ status: "failed" }), href)).toEqual({
      tone: "error",
      labelKey: "space_status_sync_error",
      fixHref: href
    });
  });

  it("treats a skipped duplicate crawl as neutral, not as an error", () => {
    expect(
      websiteStatus(
        crawl({ status: "failed", result_location: "Skipped duplicate crawl: already running" }),
        href
      )
    ).toEqual({ tone: "neutral", labelKey: "sync_skipped" });
  });
});

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
      href: "/spaces/space-1/knowledge?tab=integrations",
      content: null,
      updatedAt: null,
      status: { tone: "neutral", labelKey: "space_status_not_synced" }
    });
  });
});

describe("recentChatItems and assistantModelName", () => {
  it("puts the most recently changed first and names the model the space offers", () => {
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
    const [first, second] = recentChatItems(space, compare);
    expect(assistantModelName(space, first!)).toBe("Haiku 4.5");
    expect(assistantModelName(space, second!)).toBeNull();
    expect(
      assistantModelName(space, makeAssistant({ completion_model_id: "model-2" }) as never)
    ).toBe("claude-opus");
    expect(
      assistantModelName(space, makeAssistant({ completion_model_id: "gone" }) as never)
    ).toBeNull();
  });
});

describe("defaultModelFirst", () => {
  it("puts the organization's default model first and keeps the API order of the rest", () => {
    const models = [
      { id: "a", is_org_default: false },
      { id: "b" },
      { id: "default", is_org_default: true },
      { id: "c", is_org_default: false }
    ];
    expect(defaultModelFirst(models).map((model) => model.id)).toEqual(["default", "a", "b", "c"]);
    // A copy: the space's own list keeps its order.
    expect(models.map((model) => model.id)).toEqual(["a", "b", "default", "c"]);
  });

  it("leaves models without a default in the API order", () => {
    const models = [{ id: "b" }, { id: "a", is_org_default: false }];
    expect(defaultModelFirst(models).map((model) => model.id)).toEqual(["b", "a"]);
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
