import type { IntegrationKnowledge } from "../knowledge";
import type { Translate } from "./skip-reasons";
import { isCredentialsError } from "./source-problems";
import { combineSyncProgress, type ProgressById, type SyncProgressSummary } from "./sync-progress";
import { latestTime, summarizeIntegrationSync } from "./sync-status";

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

export type SourceView = { tab: SourceTab; folder: string | null };

export function readSourceView(search: Pick<URLSearchParams, "get">): SourceView {
  return {
    tab: sourceTabParam(search.get("tab") ?? undefined) ?? "content",
    folder: search.get("folder")
  };
}

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

/** Items whose sync was queued from here and that no worker has reported on yet. */
export type QueuedIds = ReadonlySet<string>;

const NO_QUEUED: QueuedIds = new Set();

function wrapperName(items: IntegrationKnowledge[]): string {
  const named = items.find(
    (item) => typeof item.wrapper_name === "string" && item.wrapper_name.trim() !== ""
  );
  return named?.wrapper_name ?? items[0]?.name ?? "";
}

/** The wrapper an item was imported under; only SharePoint imports group by wrapper. */
function wrapperIdOf(item: IntegrationKnowledge): string | null {
  return item.wrapper_id && item.integration_type === "sharepoint" ? item.wrapper_id : null;
}

function wrapperSource(id: string, group: IntegrationKnowledge[]): IntegrationSource | undefined {
  const [first] = group;
  if (!first) return undefined;
  return {
    kind: "wrapper",
    id,
    name: wrapperName(group),
    integrationType: first.integration_type,
    items: group,
    embeddingModelId: first.embedding_model.id
  };
}

/**
 * SharePoint items sharing a wrapper become one source; every other item is
 * its own. Sorted by name with `compare`: the locale's collator (Astryx
 * `useCollator().compare`), so the server's HTML and the browser's render agree.
 */
export function groupIntegrationSources(
  items: readonly IntegrationKnowledge[],
  compare: Intl.Collator["compare"]
): IntegrationSource[] {
  const wrappers = new Map<string, IntegrationKnowledge[]>();
  const sources: IntegrationSource[] = [];
  for (const item of items) {
    const wrapperId = wrapperIdOf(item);
    if (wrapperId) {
      const group = wrappers.get(wrapperId);
      if (group) group.push(item);
      else wrappers.set(wrapperId, [item]);
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
    const source = wrapperSource(id, group);
    if (source) sources.push(source);
  }
  return sources.sort((a, b) => compare(a.name, b.name));
}

/** One wrapper as a source; undefined when none of `items` was imported under it. */
export function findWrapperSource(
  items: readonly IntegrationKnowledge[],
  wrapperId: string
): IntegrationSource | undefined {
  return wrapperSource(
    wrapperId,
    items.filter((item) => wrapperIdOf(item) === wrapperId)
  );
}

/**
 * What this space may do to a wrapper as a whole: the first item's permissions,
 * but only when every item belongs to the space. A wrapper shared in, even in
 * part, offers no edit or delete that the backend would refuse.
 */
export function wrapperPermissions(
  items: readonly IntegrationKnowledge[],
  spaceId: string
): { canEdit: boolean; canDelete: boolean } {
  const owned = items.filter((item) => item.space_id === spaceId);
  const permissions = owned.length === items.length ? (owned[0]?.permissions ?? []) : [];
  return { canEdit: permissions.includes("edit"), canDelete: permissions.includes("delete") };
}

/** The tab a link asks for; older links name "skipped", which is now part of Problems. */
export function sourceTabParam(value: string | string[] | undefined): SourceTab | undefined {
  if (value === "problems" || value === "skipped") return "problems";
  if (value === "content" || value === "activity") return value;
  return undefined;
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

/** An item's page: its wrapper's with the item's folder chosen, or its own. */
export function itemHref(
  spaceRouteId: string,
  item: IntegrationKnowledge,
  tab?: SourceTab
): string {
  const wrapperId = wrapperIdOf(item);
  return wrapperId
    ? sourceHref(spaceRouteId, { kind: "wrapper", id: wrapperId }, { folder: item.id, tab })
    : sourceHref(spaceRouteId, { kind: "item", id: item.id }, { tab });
}

/** Whether SharePoint tells Eneo about changes to the item, from when its subscription expires. */
export type WatchState = "active" | "expiring" | "expired" | "none";

/** Subscriptions are renewed automatically from this long before they expire. */
const WATCH_EXPIRING_MS = 48 * 60 * 60 * 1000;

/** Relative to `now`, which the server and the browser see differently: read it once hydrated. */
export function itemWatchState(item: IntegrationKnowledge, now = Date.now()): WatchState {
  const expires = item.metadata?.sharepoint_subscription_expires_at;
  const left = expires ? new Date(expires).getTime() - now : Number.NaN;
  if (Number.isNaN(left)) return "none";
  if (left <= 0) return "expired";
  return left <= WATCH_EXPIRING_MS ? "expiring" : "active";
}

const WATCH_STATE_LABEL: Record<WatchState, string> = {
  active: "integration_source_watch_on",
  expiring: "integration_source_watch_state_expiring",
  expired: "integration_source_watch_state_expired",
  none: "integration_source_watch_off"
};

/** In the words of the source's "Change notifications" figure (On/Off). */
export function watchStateLabel(state: WatchState, t: Translate): string {
  return t(WATCH_STATE_LABEL[state]);
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

export function summarizeSource(
  items: readonly IntegrationKnowledge[],
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
    lastSyncedAt = latestTime(lastSyncedAt, summary.lastSyncedAt);
    lastSyncAttemptedAt = latestTime(lastSyncAttemptedAt, summary.lastSyncAttemptedAt);
    if (summary.state === "error") failedItems.push(item);
    states.push(itemState(item, progress, queued));
  }
  const syncing = items.flatMap((item) => {
    const entry = progress[item.id];
    return entry ? [entry] : [];
  });
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

/** The folders waiting for a first sync, where the source's state alone reads as more settled. */
export function waitingLabel(summary: SourceSummary, t: Translate): string | null {
  if (summary.waitingItems === 0 || summary.state === "never") return null;
  return summary.waitingItems === 1
    ? t("integration_source_waiting_one")
    : t("integration_source_waiting_other", { count: summary.waitingItems });
}

/** "3 folders, 1 file" style description of what a source holds. */
export function sourceContentsLabel(items: readonly IntegrationKnowledge[], t: Translate): string {
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
  const add = (count: number, one: string, other: string) => {
    if (count > 0) parts.push(t(count === 1 ? one : other, { count }));
  };
  add(sites, "sharepoint_wrapper_sites_one", "sharepoint_wrapper_sites_other");
  add(folders, "sharepoint_wrapper_folders_one", "sharepoint_wrapper_folders_other");
  add(files, "sharepoint_wrapper_files_one", "sharepoint_wrapper_files_other");
  if (parts.length === 0) {
    add(items.length, "wrapper_items_count_one", "wrapper_items_count_other");
  }
  return parts.join(", ");
}

/**
 * The status filters above a list of sources. A source can match several: "attention"
 * also covers one that syncs, and "never" one where only some items wait for a first sync.
 */
export type SourceFilter = "all" | "attention" | "syncing" | "never" | "empty" | "ok";

export const SOURCE_FILTERS: readonly SourceFilter[] = [
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
  const counts = { all: 0, attention: 0, syncing: 0, never: 0, empty: 0, ok: 0 };
  for (const summary of summaries) {
    for (const filter of SOURCE_FILTERS) {
      if (matchesSourceFilter(summary, filter)) counts[filter] += 1;
    }
  }
  return counts;
}

export type SourceStatus = {
  tone: "success" | "warning" | "error" | "accent" | "neutral";
  labelKey: string;
  isPulsing?: boolean;
};

/** How a source or item state shows: a coloured dot and a label that carries the meaning. */
export function sourceStateStatus(state: SourceState | ItemState): SourceStatus {
  switch (state) {
    case "syncing":
      return { tone: "accent", labelKey: "integration_source_state_syncing", isPulsing: true };
    case "queued":
      return { tone: "accent", labelKey: "integration_source_state_queued" };
    case "attention":
      return { tone: "error", labelKey: "integration_source_state_attention" };
    case "error":
      return { tone: "error", labelKey: "integration_sync_status_error" };
    case "never":
      return { tone: "neutral", labelKey: "integration_source_state_never" };
    case "empty":
      return { tone: "warning", labelKey: "integration_sync_status_empty" };
    case "ok":
      return { tone: "success", labelKey: "integration_source_state_ok" };
  }
}
