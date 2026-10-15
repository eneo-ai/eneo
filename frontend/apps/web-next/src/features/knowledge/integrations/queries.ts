import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

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
