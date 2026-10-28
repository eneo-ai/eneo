import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { isCredentialsError } from "./sourceProblems";
import { summarizeIntegrationSync } from "./syncStatus";
import {
  combineSyncProgress,
  type IntegrationSyncProgress,
  type SyncProgressSummary
} from "./syncProgress";

/**
 * What the knowledge list shows as one row: the items imported together under
 * a wrapper, or a single item imported on its own.
 */
export type IntegrationSource = {
  kind: "wrapper" | "item";
  /** The wrapper id, or the item id for a single item. */
  id: string;
  name: string;
  integrationType: IntegrationKnowledge["integration_type"];
  items: IntegrationKnowledge[];
  embeddingModelId: string;
};

export type SourceTab = "content" | "problems" | "activity";

export type SourceState = "syncing" | "queued" | "attention" | "never" | "empty" | "ok";

export type ItemState = "syncing" | "queued" | "error" | "never" | "empty" | "ok";

export type SourceSummary = {
  state: SourceState;
  documentCount: number;
  lastSyncedAt: string | null;
  lastSyncAttemptedAt: string | null;
  failedItems: IntegrationKnowledge[];
  /** Items that have not finished a first sync and are not syncing now. */
  waitingItems: number;
  /** Items whose sync this person queued and that no worker has reported on yet. */
  queuedItems: number;
  /** Every failure is the organisation's SharePoint sign-in, which only an admin can fix. */
  credentialsFailed: boolean;
  progress: SyncProgressSummary | null;
};

type ProgressById = Readonly<Record<string, IntegrationSyncProgress>>;
type QueuedIds = ReadonlySet<string>;

const NO_QUEUED: QueuedIds = new Set();

function wrapperName(items: IntegrationKnowledge[]): string {
  const named = items.find(
    (item) => typeof item.wrapper_name === "string" && item.wrapper_name.trim() !== ""
  );
  return named?.wrapper_name ?? items[0].name;
}

/** SharePoint items sharing a wrapper become one source; every other item is its own. */
export function groupIntegrationSources(items: IntegrationKnowledge[]): IntegrationSource[] {
  const wrappers = new Map<string, IntegrationKnowledge[]>();
  const sources: IntegrationSource[] = [];
  for (const item of items) {
    if (item.wrapper_id && item.integration_type === "sharepoint") {
      const group = wrappers.get(item.wrapper_id);
      if (group) group.push(item);
      else wrappers.set(item.wrapper_id, [item]);
      continue;
    }
    sources.push({
      kind: "item",
      id: item.id,
      name: item.name,
      integrationType: item.integration_type,
      items: [item],
      embeddingModelId: item.embedding_model.id
    });
  }
  for (const [id, group] of wrappers) {
    sources.push({
      kind: "wrapper",
      id,
      name: wrapperName(group),
      integrationType: group[0].integration_type,
      items: group,
      embeddingModelId: group[0].embedding_model.id
    });
  }
  return sources.sort((a, b) => a.name.localeCompare(b.name));
}

/** Unique across the sources of a space: a wrapper and an item never share an id. */
export function sourceKey(source: Pick<IntegrationSource, "kind" | "id">): string {
  return `${source.kind}:${source.id}`;
}

export function sourceHref(
  spaceRouteId: string,
  source: Pick<IntegrationSource, "kind" | "id">,
  params: { folder?: string | null; tab?: SourceTab } = {}
): string {
  const base =
    source.kind === "wrapper"
      ? `/spaces/${spaceRouteId}/knowledge/integrations/wrapper/${source.id}`
      : `/spaces/${spaceRouteId}/knowledge/integrations/${source.id}`;
  const query = new URLSearchParams();
  if (params.folder) query.set("folder", params.folder);
  if (params.tab) query.set("tab", params.tab);
  const search = query.toString();
  return search ? `${base}?${search}` : base;
}

/** Whether SharePoint tells Eneo about changes to the item, from when its subscription expires. */
export type WatchState = "active" | "expiring" | "expired" | "none";

/** Subscriptions are renewed automatically from this long before they expire. */
const WATCH_EXPIRING_MS = 48 * 60 * 60 * 1000;

export function itemWatchState(item: IntegrationKnowledge, now = Date.now()): WatchState {
  const expires = item.metadata?.sharepoint_subscription_expires_at;
  const left = expires ? new Date(expires).getTime() - now : Number.NaN;
  if (Number.isNaN(left)) return "none";
  if (left <= 0) return "expired";
  return left <= WATCH_EXPIRING_MS ? "expiring" : "active";
}

/** In the words of the source's "Change notifications" figure (On/Off). */
export function watchStateLabel(state: WatchState): string {
  switch (state) {
    case "active":
      return m.integration_source_watch_on();
    case "expiring":
      return m.integration_source_watch_state_expiring();
    case "expired":
      return m.integration_source_watch_state_expired();
    case "none":
      return m.integration_source_watch_off();
  }
}

export function itemState(
  item: IntegrationKnowledge,
  progress: ProgressById,
  queued: QueuedIds = NO_QUEUED
): ItemState {
  if (progress[item.id]) return "syncing";
  if (queued.has(item.id)) return "queued";
  const state = summarizeIntegrationSync(item).state;
  return state === "success" ? "ok" : state;
}

function latest(a: string | null, b: string | null): string | null {
  if (!a) return b;
  if (!b) return a;
  return new Date(a).getTime() >= new Date(b).getTime() ? a : b;
}

export function summarizeSource(
  items: IntegrationKnowledge[],
  progress: ProgressById,
  queued: QueuedIds = NO_QUEUED
): SourceSummary {
  let documentCount = 0;
  let lastSyncedAt: string | null = null;
  let lastSyncAttemptedAt: string | null = null;
  const failedItems: IntegrationKnowledge[] = [];
  const states: ItemState[] = [];
  for (const item of items) {
    const summary = summarizeIntegrationSync(item);
    documentCount += summary.documentCount;
    lastSyncedAt = latest(lastSyncedAt, summary.lastSyncedAt);
    lastSyncAttemptedAt = latest(lastSyncAttemptedAt, summary.lastSyncAttemptedAt);
    if (summary.state === "error") failedItems.push(item);
    states.push(itemState(item, progress, queued));
  }
  const syncing = items.map((item) => progress[item.id]).filter((entry) => entry !== undefined);
  const queuedItems = states.filter((s) => s === "queued").length;

  let state: SourceState;
  if (syncing.length > 0) state = "syncing";
  else if (queuedItems > 0) state = "queued";
  else if (failedItems.length > 0) state = "attention";
  else if (states.every((s) => s === "never")) state = "never";
  else if (documentCount === 0) state = "empty";
  else state = "ok";

  return {
    state,
    documentCount,
    lastSyncedAt,
    lastSyncAttemptedAt,
    failedItems,
    waitingItems: states.filter((s) => s === "never").length,
    queuedItems,
    credentialsFailed:
      failedItems.length > 0 &&
      failedItems.every((item) => isCredentialsError(item.metadata?.last_sync_error)),
    progress: combineSyncProgress(syncing)
  };
}

/** A sync of the source is queued or running: starting one now would only queue a second. */
export function isSyncActive(summary: Pick<SourceSummary, "progress" | "queuedItems">): boolean {
  return summary.progress !== null || summary.queuedItems > 0;
}

/** "SharePoint · 3 folders" style description of what a source holds. */
export function sourceContentsLabel(items: IntegrationKnowledge[]): string {
  let files = 0;
  let folders = 0;
  let sites = 0;
  for (const item of items) {
    const type = (item.selected_item_type ?? "").toLowerCase();
    if (type === "file") files += 1;
    else if (type === "folder") folders += 1;
    else if (type === "site_root" || type === "site") sites += 1;
  }
  const parts: string[] = [];
  if (sites > 0) {
    parts.push(
      sites === 1
        ? m.sharepoint_wrapper_sites_one({ count: sites })
        : m.sharepoint_wrapper_sites_other({ count: sites })
    );
  }
  if (folders > 0) {
    parts.push(
      folders === 1
        ? m.sharepoint_wrapper_folders_one({ count: folders })
        : m.sharepoint_wrapper_folders_other({ count: folders })
    );
  }
  if (files > 0) {
    parts.push(
      files === 1
        ? m.sharepoint_wrapper_files_one({ count: files })
        : m.sharepoint_wrapper_files_other({ count: files })
    );
  }
  if (parts.length === 0) {
    parts.push(
      items.length === 1
        ? m.wrapper_items_count_one({ count: items.length })
        : m.wrapper_items_count_other({ count: items.length })
    );
  }
  return parts.join(", ");
}

/**
 * The status filters above a list of sources. A source can match several: "attention"
 * also covers one that syncs, and "never" one where only some items wait for a first sync.
 */
export type SourceFilter = "all" | "attention" | "syncing" | "never" | "empty" | "ok";

export const SOURCE_FILTERS: SourceFilter[] = [
  "all",
  "attention",
  "syncing",
  "never",
  "empty",
  "ok"
];

export function matchesSourceFilter(summary: SourceSummary, filter: SourceFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "attention":
      return summary.failedItems.length > 0;
    case "syncing":
      return isSyncActive(summary);
    case "never":
      return summary.waitingItems > 0;
    default:
      return summary.state === filter;
  }
}

export function countSourceFilters(
  summaries: readonly SourceSummary[]
): Record<SourceFilter, number> {
  const counts = Object.fromEntries(SOURCE_FILTERS.map((filter) => [filter, 0])) as Record<
    SourceFilter,
    number
  >;
  for (const summary of summaries) {
    for (const filter of SOURCE_FILTERS) {
      if (matchesSourceFilter(summary, filter)) counts[filter] += 1;
    }
  }
  return counts;
}
