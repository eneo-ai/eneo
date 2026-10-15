import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { SkippedDocuments } from "./source-problems";
import type { ProgressById } from "./sync-progress";

export type UserIntegration = Schema<"UserIntegration">;
export type IntegrationPreview = Schema<"IntegrationPreviewData">;
export type SharePointTreeItem = Schema<"SharePointTreeItem">;
export type SharePointTree = Schema<"SharePointTreeResponse">;
export type SyncLog = Schema<"SyncLog">;
export type SyncLogPage = Schema<"PaginatedSyncLogList">;

export const SYNC_LOG_PAGE_SIZE = 10;

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

export function syncLogsQueryOptions(api: EneoClient, knowledgeId: string, page: number) {
  return queryOptions({
    queryKey: ["integrations", "sync-logs", knowledgeId, page],
    queryFn: (): Promise<SyncLogPage> =>
      unwrap(
        api.GET("/api/v1/integrations/sync-logs/{integration_knowledge_id}/", {
          params: {
            path: { integration_knowledge_id: knowledgeId },
            query: { skip: (page - 1) * SYNC_LOG_PAGE_SIZE, limit: SYNC_LOG_PAGE_SIZE }
          }
        })
      )
  });
}

export type IntegrationDocumentsPage = Schema<"IntegrationDocumentsPage">;
export type IntegrationDocument = Schema<"IntegrationDocumentItem">;
export type IntegrationDocumentsSort = "name" | "path" | "size" | "updated_at";

export const DOCUMENTS_PAGE_SIZE = 50;

/** One page of a synced item's documents; `q` matches the title, the path or a property value. */
export function integrationDocumentsQueryOptions(
  api: EneoClient,
  args: {
    spaceId: string;
    knowledgeId: string;
    q: string;
    sort: IntegrationDocumentsSort;
    order: "asc" | "desc";
    page: number;
    /** Changes when the item's last sync does, so a finished sync refetches. */
    revision: string;
  }
) {
  return queryOptions({
    queryKey: ["integrations", "documents", args],
    queryFn: (): Promise<IntegrationDocumentsPage> =>
      unwrap(
        api.GET(
          "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/documents/",
          {
            params: {
              path: { id: args.spaceId, integration_knowledge_id: args.knowledgeId },
              query: {
                q: args.q.trim() || undefined,
                sort: args.sort,
                order: args.order,
                limit: DOCUMENTS_PAGE_SIZE,
                offset: (args.page - 1) * DOCUMENTS_PAGE_SIZE
              }
            }
          }
        )
      ),
    placeholderData: (previous) => previous
  });
}

/**
 * The files the latest sync of an item could not read, capped by the backend.
 * `revision` changes with the item's last sync, which rewrites the list.
 */
export function skippedDocumentsQueryOptions(
  api: EneoClient,
  spaceId: string,
  knowledgeId: string,
  revision: string
) {
  return queryOptions({
    queryKey: ["integrations", "skipped", spaceId, knowledgeId, revision],
    // The key changes when a sync rewrites the list, so a cached one stays right.
    staleTime: 5 * 60_000,
    queryFn: (): Promise<SkippedDocuments> =>
      unwrap(
        api.GET(
          "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/documents/skipped/",
          { params: { path: { id: spaceId, integration_knowledge_id: knowledgeId } } }
        )
      )
  });
}

/** An item's newest sync logs, `limit` of them; the activity view grows the window. */
export function recentSyncLogsQueryOptions(api: EneoClient, knowledgeId: string, limit: number) {
  return queryOptions({
    queryKey: ["integrations", "sync-logs", knowledgeId, "recent", limit],
    queryFn: (): Promise<SyncLogPage> =>
      unwrap(
        api.GET("/api/v1/integrations/sync-logs/{integration_knowledge_id}/", {
          params: { path: { integration_knowledge_id: knowledgeId }, query: { skip: 0, limit } }
        })
      ),
    placeholderData: (previous) => previous
  });
}

const PROGRESS_ACTIVE_MS = 2_000;
const PROGRESS_IDLE_MS = 15_000;

function isNotFound(error: unknown): boolean {
  return error instanceof EneoApiError && error.status === 404;
}

/**
 * The running syncs of a space, keyed by item. Polls every 2 s while one runs
 * and every 15 s otherwise; stops for good on a 404 (a backend without the
 * endpoint). Structural sharing keeps the data stable between identical polls.
 */
export function syncProgressQueryOptions(api: EneoClient, spaceId: string) {
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
    retry: (failures, error) => !isNotFound(error) && failures < 2,
    refetchInterval: (query) => {
      if (isNotFound(query.state.error)) return false;
      return Object.keys(query.state.data ?? {}).length > 0 ? PROGRESS_ACTIVE_MS : PROGRESS_IDLE_MS;
    }
  });
}

export type KnowledgeOverview = Schema<"AdminIntegrationKnowledgeOverview">;

/** Every source in shared and organisation spaces; personal spaces are only counted. */
export function knowledgeOverviewQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["integrations", "admin-overview"],
    queryFn: (): Promise<KnowledgeOverview> =>
      unwrap(api.GET("/api/v1/admin/integrations/knowledge/"))
  });
}
