import type { ChatAppItem } from "@/features/assistants/assistants";
import { groupIntegrationRows } from "@/features/knowledge/integrations/grouping";
import {
  formatWebsiteName,
  type Collection,
  type IntegrationKnowledge,
  type Website
} from "@/features/knowledge/knowledge";
import { websiteStatus, type KnowledgeStatus } from "@/features/knowledge/website-status";
import type { Space, SpaceRouteId } from "../space";

/** Locale-aware string order: `collator.compare` from Astryx `useCollator()`. */
export type Compare = (a: string, b: string) => number;

function time(value: string | null | undefined): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * A space's models with the organization's default model first (when the
 * space offers it, new assistants, apps and services start with it); the rest
 * keep the API's order.
 */
export function defaultModelFirst<Model extends { is_org_default?: boolean }>(
  models: readonly Model[]
): Model[] {
  return [...models].sort(
    (a, b) => Number(b.is_org_default === true) - Number(a.is_org_default === true)
  );
}

/** Assistants and group chats, most recently changed first. */
export function recentChatItems(space: Space, compare: Compare): ChatAppItem[] {
  return [
    ...(space.applications?.assistants.items ?? []),
    ...(space.applications?.group_chats.items ?? [])
  ].sort((a, b) => time(b.updated_at) - time(a.updated_at) || compare(a.name, b.name));
}

export type KnowledgeKind = "collection" | "website" | "integration";

/** One row of the overview's knowledge table. */
export type KnowledgeRow = {
  key: string;
  kind: KnowledgeKind;
  name: string;
  href: string;
  /** Translation key and values for the Innehåll column; null when unknown. */
  content: { key: string; values: Record<string, string | number> } | null;
  status: KnowledgeStatus;
  updatedAt: string | null;
  source:
    | { kind: "collection"; collection: Collection }
    | { kind: "website"; website: Website }
    | { kind: "integration"; item: IntegrationKnowledge }
    | { kind: "wrapper"; wrapperId: string; wrapperName: string; items: IntegrationKnowledge[] };
};

function latest(values: (string | null | undefined)[]): string | null {
  let best: string | null = null;
  for (const value of values) {
    if (value && time(value) > time(best)) best = value;
  }
  return best;
}

/**
 * The space's own collections, websites and integrations as one list, most
 * recently updated first. Items shared in from other spaces are left out, as
 * on the knowledge page.
 */
export function overviewKnowledgeRows(
  space: Space,
  routeId: SpaceRouteId,
  compare: Compare
): KnowledgeRow[] {
  const base = `/spaces/${routeId}/knowledge`;
  const own = (item: { space_id: string }) => item.space_id === space.id;
  const rows: KnowledgeRow[] = [];

  for (const collection of space.knowledge.groups.items.filter(own)) {
    const files = collection.metadata.num_info_blobs;
    rows.push({
      key: `collection-${collection.id}`,
      kind: "collection",
      name: collection.name,
      href: `${base}/collections/${collection.id}`,
      content: { key: "space_files_count", values: { count: files } },
      status:
        files > 0
          ? { tone: "success", labelKey: "space_status_indexed" }
          : { tone: "neutral", labelKey: "empty" },
      updatedAt: collection.updated_at ?? collection.created_at ?? null,
      source: { kind: "collection", collection }
    });
  }

  for (const website of space.knowledge.websites.items.filter(own)) {
    const href = `${base}/websites/${website.id}`;
    const pages = website.latest_crawl?.pages_crawled;
    rows.push({
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
    });
  }

  const integrations = space.knowledge.integration_knowledge_list.items.filter(own);
  for (const row of groupIntegrationRows(integrations)) {
    const items = row.kind === "wrapper" ? row.items : [row.item];
    const syncedAt = latest(items.map((item) => item.metadata.last_synced_at));
    const status: KnowledgeStatus = syncedAt
      ? { tone: "success", labelKey: "space_status_synced" }
      : { tone: "neutral", labelKey: "space_status_not_synced" };
    if (row.kind === "wrapper") {
      rows.push({
        key: `wrapper-${row.wrapperId}`,
        kind: "integration",
        name: row.wrapperName,
        href: `${base}/integrations/wrapper/${row.wrapperId}`,
        content: { key: "space_items_count", values: { count: row.items.length } },
        status,
        updatedAt: syncedAt,
        source: {
          kind: "wrapper",
          wrapperId: row.wrapperId,
          wrapperName: row.wrapperName,
          items: row.items
        }
      });
    } else {
      rows.push({
        key: `integration-${row.item.id}`,
        kind: "integration",
        name: row.item.name,
        href: `${base}?tab=integrations`,
        content: null,
        status,
        updatedAt: syncedAt,
        source: { kind: "integration", item: row.item }
      });
    }
  }

  return rows.sort((a, b) => time(b.updatedAt) - time(a.updatedAt) || compare(a.name, b.name));
}

/**
 * Own collections the user may add files to, for the overview's upload menu.
 * Like the collection page, a collection whose embedding model the space no
 * longer offers takes no uploads.
 */
export function uploadTargets(space: Space, compare: Compare): Collection[] {
  const models = new Set(space.embedding_models.map((model) => model.id));
  return space.knowledge.groups.items
    .filter(
      (collection) =>
        collection.space_id === space.id &&
        (collection.permissions ?? []).includes("edit") &&
        models.has(collection.embedding_model.id)
    )
    .sort((a, b) => compare(a.name, b.name));
}
