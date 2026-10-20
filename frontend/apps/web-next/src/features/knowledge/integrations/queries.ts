import { createSyncDetailsLoader } from "@eneo/eneo-js/integrations/sync-details";
import { queryOptions, type Query, type QueryClient, type QueryKey } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { IntegrationKnowledge } from "../knowledge";
import type { SkippedDocuments } from "./source-problems";
import { continueWindow, mergeFirstPage } from "./sync-activity";
import type { ProgressById } from "./sync-progress";
import { compareSyncRevisions, syncRevision } from "./sync-status";

const detailLoaders = new WeakMap<EneoClient, ReturnType<typeof createSyncDetailsLoader>>();

function syncDetails(
  api: EneoClient,
  spaceId: string,
  itemId: string,
  offset: number,
  limit: number
) {
  let load = detailLoaders.get(api);
  if (!load) {
    load = createSyncDetailsLoader((id, body) =>
      unwrap(
        api.POST("/api/v1/spaces/{id}/knowledge/integrations/sync-details/", {
          params: { path: { id } },
          body
        })
      )
    );
    detailLoaders.set(api, load);
  }
  return load(spaceId, itemId, offset, limit);
}

export type UserIntegration = Schema<"UserIntegration">;
export type IntegrationPreview = Schema<"IntegrationPreviewData">;
export type SharePointTreeItem = Schema<"SharePointTreeItem">;
export type SharePointTree = Schema<"SharePointTreeResponse">;
export type SyncLog = Schema<"SyncLog">;
export type SyncLogPage = Schema<"PaginatedSyncLogList">;

/** Integrations the backend offers for this space (filtered by space/auth type). */
export function availableIntegrationsQueryOptions(api: EneoClient, spaceId: string) {
  return queryOptions({
    queryKey: ["integrations", "available", spaceId],
    queryFn: async (): Promise<UserIntegration[]> => {
      const page = await unwrap(
        api.GET("/api/v1/integrations/spaces/{space_id}/available/", {
          params: { path: { space_id: spaceId } }
        })
      );
      return [...page.items].sort((a, b) => a.name.localeCompare(b.name));
    }
  });
}

/** Importable top-level resources (SharePoint sites / Confluence spaces). */
export function integrationPreviewQueryOptions(api: EneoClient, userIntegrationId: string) {
  return queryOptions({
    queryKey: ["integrations", "preview", userIntegrationId],
    queryFn: async (): Promise<IntegrationPreview[]> => {
      const page = await unwrap(
        api.GET("/api/v1/integrations/{user_integration_id}/preview/", {
          params: { path: { user_integration_id: userIntegrationId } }
        })
      );
      return page.items;
    }
  });
}

export function sharepointTreeQueryOptions(
  api: EneoClient,
  args: {
    userIntegrationId: string;
    spaceId: string;
    siteId?: string;
    driveId?: string;
    folderId?: string;
    folderPath?: string;
  }
) {
  return queryOptions({
    queryKey: ["integrations", "sharepoint-tree", args],
    queryFn: (): Promise<SharePointTree> =>
      unwrap(
        api.GET("/api/v1/integrations/{user_integration_id}/sharepoint/tree/", {
          params: {
            path: { user_integration_id: args.userIntegrationId },
            query: {
              space_id: args.spaceId,
              site_id: args.siteId,
              drive_id: args.driveId,
              folder_id: args.folderId,
              folder_path: args.folderPath
            }
          }
        })
      )
  });
}

export type IntegrationDocumentsPage = Schema<"IntegrationDocumentsPage">;
export type IntegrationDocument = Schema<"IntegrationDocumentItem">;
export type IntegrationDocumentsSort = "name" | "path" | "size" | "updated_at";

export const DOCUMENTS_PAGE_SIZE = 50;

// The lists a sync rewrites (documents, skipped files, sync logs) carry the
// item's sync revision in their key: a sync that finished while they were not
// on screen loads them again, and the list shown before stays until it has.

/**
 * The query of an item's newest revision with data under `itemKey` (the key
 * before the revision), such as the list of an earlier revision while the
 * current one loads. A new key in `useQueries` gets a new observer, which has
 * no previous data for `placeholderData` to keep. By revision, not by when
 * the data was written: an older page can still land in an earlier revision.
 */
function latestCachedQuery(queryClient: QueryClient, itemKey: QueryKey): Query | undefined {
  const revision = (query: Query) => String(query.queryKey[itemKey.length] ?? "");
  const [latest] = queryClient
    .getQueryCache()
    .findAll({ queryKey: itemKey })
    .filter((query) => query.state.data !== undefined)
    .sort(
      (a, b) =>
        compareSyncRevisions(revision(b), revision(a)) ||
        b.state.dataUpdatedAt - a.state.dataUpdatedAt
    );
  return latest;
}

function latestCached<T>(queryClient: QueryClient, itemKey: QueryKey): T | undefined {
  return latestCachedQuery(queryClient, itemKey)?.state.data as T | undefined;
}

/** One page of a synced item's documents; `q` matches the title, the path or a property value. */
export function integrationDocumentsQueryOptions(
  api: EneoClient,
  args: {
    spaceId: string;
    item: IntegrationKnowledge;
    q: string;
    sort: IntegrationDocumentsSort;
    order: "asc" | "desc";
    page: number;
  }
) {
  const { spaceId, item, ...view } = args;
  const knowledgeId = item.id;
  return queryOptions({
    queryKey: ["integrations", "documents", spaceId, knowledgeId, syncRevision(item), view],
    queryFn: (): Promise<IntegrationDocumentsPage> =>
      unwrap(
        api.GET(
          "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/documents/",
          {
            params: {
              path: { id: spaceId, integration_knowledge_id: knowledgeId },
              query: {
                q: view.q.trim() || undefined,
                sort: view.sort,
                order: view.order,
                limit: DOCUMENTS_PAGE_SIZE,
                offset: (view.page - 1) * DOCUMENTS_PAGE_SIZE
              }
            }
          }
        )
      ),
    placeholderData: (previous) => previous
  });
}

/** The files the latest sync of an item could not read, capped by the backend. */
export function skippedDocumentsQueryOptions(
  api: EneoClient,
  queryClient: QueryClient,
  spaceId: string,
  item: IntegrationKnowledge
) {
  const itemKey = ["integrations", "skipped", spaceId, item.id];
  return queryOptions({
    queryKey: [...itemKey, syncRevision(item)],
    // Only a sync rewrites the list, and its revision is in the key.
    staleTime: 5 * 60_000,
    queryFn: async (): Promise<SkippedDocuments> => {
      const details = await syncDetails(api, spaceId, item.id, 0, 1);
      if (details.skipped === null) throw new Error("Missing skipped files in first sync page");
      return details.skipped;
    },
    placeholderData: () => latestCached<SkippedDocuments>(queryClient, itemKey)
  });
}

/** A bounded window per import; long histories are read page by page. */
export const SYNC_LOG_PAGE_SIZE = 10;

/** One page of an item's sync logs, newest first, from the `skip`th. */
export async function fetchSyncLogPage(
  api: EneoClient,
  spaceId: string,
  knowledgeId: string,
  skip: number
): Promise<SyncLogPage> {
  return (await syncDetails(api, spaceId, knowledgeId, skip, SYNC_LOG_PAGE_SIZE)).history;
}

/** An item's sync logs as loaded so far, newest first, and how many it has in all. */
export type SyncLogWindow = { logs: SyncLog[]; total: number };

const syncLogItemKey = (spaceId: string, itemId: string) => [
  "integrations",
  "sync-logs",
  spaceId,
  itemId
];

/**
 * The sync history an item shows: its current revision's window, or while
 * that loads (or after it failed to) the newest one cached before it.
 */
export function shownSyncLogWindow(
  queryClient: QueryClient,
  spaceId: string,
  itemId: string
): SyncLogWindow | undefined {
  return latestCached<SyncLogWindow>(queryClient, syncLogItemKey(spaceId, itemId));
}

/**
 * Adds an older page to the history the item shows now (`shownSyncLogWindow`),
 * which a new revision may have replaced since the page was asked for; while
 * the new one loads, its first page takes the page over from there. A page
 * that does not continue that history is dropped (`continueWindow`), and
 * "show older" asks again from where it now ends.
 */
export function addOlderSyncLogs(
  queryClient: QueryClient,
  spaceId: string,
  itemId: string,
  page: Pick<SyncLogPage, "items" | "total_count">,
  after: string | undefined
): void {
  const query = latestCachedQuery(queryClient, syncLogItemKey(spaceId, itemId));
  const shown = query?.state.data as SyncLogWindow | undefined;
  const next = shown ? continueWindow(shown, page, after) : null;
  if (query && next) queryClient.setQueryData<SyncLogWindow>(query.queryKey, next);
}

/**
 * An item's sync history: its newest page, and the older pages "show older"
 * adds to the window (`addOlderSyncLogs`). A new revision loads the newest
 * page again and keeps the older pages loaded before when it reaches them.
 */
export function syncLogWindowQueryOptions(
  api: EneoClient,
  queryClient: QueryClient,
  spaceId: string,
  item: IntegrationKnowledge
) {
  const latest = () => shownSyncLogWindow(queryClient, spaceId, item.id);
  return queryOptions({
    queryKey: [...syncLogItemKey(spaceId, item.id), syncRevision(item)],
    queryFn: async (): Promise<SyncLogWindow> => {
      const page = await fetchSyncLogPage(api, spaceId, item.id, 0);
      return {
        logs: mergeFirstPage(latest()?.logs, page.items, page.total_count),
        total: page.total_count
      };
    },
    placeholderData: latest
  });
}

const PROGRESS_ACTIVE_MS = 2_000;
const PROGRESS_IDLE_MS = 15_000;

/** No endpoint (an older backend), or no access to the space any more: asking again won't help. */
function isUnavailable(error: unknown): boolean {
  return (
    error instanceof EneoApiError &&
    (error.status === 404 || error.status === 403 || error.status === 401)
  );
}

/**
 * The running syncs of a space, keyed by item. Polls every 2 s while one runs
 * or an item of `awaiting` (a sync queued from here) has not reported yet, and
 * every 15 s otherwise, but not while the browser tab is hidden; stops for
 * good on a 404 (a backend without the endpoint) or a refusal (401, 403). Structural sharing keeps the
 * data stable between identical polls.
 */
export function syncProgressQueryOptions(
  api: EneoClient,
  spaceId: string,
  awaiting: readonly string[] = []
) {
  return queryOptions({
    queryKey: ["integrations", "sync-progress", spaceId],
    queryFn: async (): Promise<ProgressById> => {
      const list = await unwrap(
        api.GET("/api/v1/spaces/{id}/knowledge/integrations/sync-progress/", {
          params: { path: { id: spaceId } }
        })
      );
      return Object.fromEntries(list.items.map((entry) => [entry.integration_knowledge_id, entry]));
    },
    retry: (failures, error) => !isUnavailable(error) && failures < 2,
    refetchInterval: (query) => {
      if (isUnavailable(query.state.error)) return false;
      const progress = query.state.data ?? {};
      const busy = Object.keys(progress).length > 0 || awaiting.some((id) => !(id in progress));
      return busy ? PROGRESS_ACTIVE_MS : PROGRESS_IDLE_MS;
    },
    refetchIntervalInBackground: false
  });
}
