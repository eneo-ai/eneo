import type { SpaceRouteId } from "@/features/spaces/space";
import {
  sourceHref,
  sourceStateStatus,
  type IntegrationSource,
  type SourceSummary
} from "./integrations/sources";
import {
  formatWebsiteName,
  type Collection,
  type IntegrationKnowledge,
  type Website
} from "./knowledge";
import { websiteStatus, type KnowledgeStatus } from "./website-status";

export type KnowledgeKind = "collection" | "website" | "integration";

/**
 * A collection, website or integration source as one row: what it holds, its
 * state with a fix link when it needs one, and when it last changed. The
 * space overview's list and the Kunskap tab's phone rows read the same rows.
 */
export type KnowledgeRow = {
  key: string;
  kind: KnowledgeKind;
  name: string;
  href: string;
  /** Translation key and values for the content summary; null when unknown. */
  content: { key: string; values: Record<string, string | number> } | null;
  status: KnowledgeStatus;
  updatedAt: string | null;
  source:
    | { kind: "collection"; collection: Collection }
    | { kind: "website"; website: Website }
    | { kind: "integration"; item: IntegrationKnowledge }
    | { kind: "wrapper"; wrapperId: string; wrapperName: string; items: IntegrationKnowledge[] };
};

function time(value: string | null | undefined): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

function latest(values: (string | null | undefined)[]): string | null {
  let best: string | null = null;
  for (const value of values) {
    if (value && time(value) > time(best)) best = value;
  }
  return best;
}

/** `/spaces/<route id>/knowledge`, the base of every row's link. */
export function knowledgeBase(routeId: SpaceRouteId): string {
  return `/spaces/${routeId}/knowledge`;
}

export function collectionRow(collection: Collection, routeId: SpaceRouteId): KnowledgeRow {
  const files = collection.metadata.num_info_blobs;
  return {
    key: `collection-${collection.id}`,
    kind: "collection",
    name: collection.name,
    href: `${knowledgeBase(routeId)}/collections/${collection.id}`,
    content: { key: "space_files_count", values: { count: files } },
    status:
      files > 0
        ? { tone: "success", labelKey: "space_status_indexed" }
        : { tone: "neutral", labelKey: "empty" },
    updatedAt: collection.updated_at ?? collection.created_at ?? null,
    source: { kind: "collection", collection }
  };
}

export function websiteRow(website: Website, routeId: SpaceRouteId): KnowledgeRow {
  const href = `${knowledgeBase(routeId)}/websites/${website.id}`;
  // What the latest run left indexed: the pages it indexed and those it found unchanged.
  const crawl = website.latest_crawl;
  const pages = crawl ? (crawl.pages_crawled ?? 0) + (crawl.pages_unchanged ?? 0) : null;
  return {
    key: `website-${website.id}`,
    kind: "website",
    name: formatWebsiteName(website),
    href,
    content: pages == null ? null : { key: "space_pages_count", values: { count: pages } },
    status: websiteStatus(website, href),
    updatedAt:
      latest([
        website.latest_crawl?.finished_at,
        website.latest_crawl?.created_at,
        website.updated_at
      ]) ?? null,
    source: { kind: "website", website }
  };
}

/** A source (one item, or a wrapper of items) with its summary of their state. */
export function sourceRow(
  source: IntegrationSource,
  summary: SourceSummary,
  routeId: SpaceRouteId
): KnowledgeRow {
  const { tone, labelKey, isPulsing } = sourceStateStatus(summary.state);
  const [single] = source.items;
  return {
    key: `${source.kind === "wrapper" ? "wrapper" : "integration"}-${source.id}`,
    kind: "integration",
    name: source.name,
    href: sourceHref(routeId, source),
    content: { key: "space_documents_count", values: { count: summary.documentCount } },
    status: {
      tone,
      labelKey,
      ...(isPulsing ? { isPulsing } : {}),
      ...(summary.state === "attention"
        ? { fixHref: sourceHref(routeId, source, { tab: "problems" }) }
        : {})
    },
    updatedAt: summary.lastSyncedAt,
    source:
      source.kind === "wrapper" || !single
        ? { kind: "wrapper", wrapperId: source.id, wrapperName: source.name, items: source.items }
        : { kind: "integration", item: single }
  };
}

/** Whether a row shows its state: a healthy one says nothing more than its content. */
export function rowNeedsStatus(row: KnowledgeRow): boolean {
  // A collection is indexed or empty, and its file count already says which.
  return row.status.tone !== "success" && row.kind !== "collection";
}
