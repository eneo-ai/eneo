import type { ChatAppItem } from "@/features/assistants/assistants";
import {
  groupIntegrationSources,
  summarizeSource
} from "@/features/knowledge/integrations/sources";
import type { Collection } from "@/features/knowledge/knowledge";
import {
  collectionRow,
  sourceRow,
  websiteRow,
  type KnowledgeRow
} from "@/features/knowledge/knowledge-rows";
import type { Space, SpaceRouteId } from "../space";

/** Locale-aware string order: `collator.compare` from Astryx `useCollator()`. */
export type Compare = (a: string, b: string) => number;

function time(value: string | null | undefined): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** Assistants and group chats, most recently changed first. */
export function recentChatItems(space: Space, compare: Compare): ChatAppItem[] {
  return [
    ...(space.applications?.assistants.items ?? []),
    ...(space.applications?.group_chats.items ?? [])
  ].sort((a, b) => time(b.updated_at) - time(a.updated_at) || compare(a.name, b.name));
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
  const own = (item: { space_id: string }) => item.space_id === space.id;
  const integrations = space.knowledge.integration_knowledge_list.items.filter(own);
  return [
    ...space.knowledge.groups.items
      .filter(own)
      .map((collection) => collectionRow(collection, routeId)),
    ...space.knowledge.websites.items.filter(own).map((website) => websiteRow(website, routeId)),
    // The overview does not poll sync progress; a running sync shows on the source itself.
    ...groupIntegrationSources(integrations, compare).map((source) =>
      sourceRow(source, summarizeSource(source.items, {}), routeId)
    )
  ].sort((a, b) => time(b.updatedAt) - time(a.updatedAt) || compare(a.name, b.name));
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
