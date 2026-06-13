import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type AuditLog = Schema<"AuditLogResponse">;
export type ActionType = Schema<"ActionType">;
export type CategoryType = Schema<"CategoryType">;
export type ActionConfig = Schema<"ActionConfig">;
export type RetentionPolicy = Schema<"RetentionPolicyResponse">;
export type ExportJobStatus = Schema<"ExportJobStatusResponse">;

export const AUDIT_PAGE_SIZE = 100;

export type AuditFilters = {
  page: number;
  from_date?: string;
  to_date?: string;
  actions: ActionType[];
  search: string;
  /** Actor-by-user filter: switches to the per-user log endpoint when set. */
  userId?: string;
  /** Display label (email) for the selected user, for the active-filter chip. */
  userLabel?: string;
};

/** Display label for an action / category — keys come from the converted catalogs. */
export function actionLabel(t: (key: string) => string, action: ActionType): string {
  return t(`audit_action_${action}`);
}
export function categoryLabel(t: (key: string) => string, category: CategoryType): string {
  return t(`audit_category_${category}`);
}

export function auditLogsQueryOptions(api: EneoClient, filters: AuditFilters) {
  const search = filters.search.trim();
  return queryOptions({
    queryKey: ["audit-logs", filters],
    retry: false, // a 401 here means "needs an access session", not a transient error
    queryFn: () => {
      // Actor-by-user filter (GDPR Art. 15 view): the per-user endpoint only
      // takes a date range + paging — action/search filters don't apply.
      if (filters.userId) {
        return unwrap(
          api.GET("/api/v1/audit/logs/user/{user_id}", {
            params: {
              path: { user_id: filters.userId },
              query: {
                page: filters.page,
                page_size: AUDIT_PAGE_SIZE,
                from_date: filters.from_date || undefined,
                to_date: filters.to_date || undefined
              }
            }
          })
        );
      }
      return unwrap(
        api.GET("/api/v1/audit/logs", {
          params: {
            query: {
              page: filters.page,
              page_size: AUDIT_PAGE_SIZE,
              from_date: filters.from_date || undefined,
              to_date: filters.to_date || undefined,
              actions: filters.actions.length > 0 ? filters.actions : undefined,
              search: search || undefined
            }
          }
        })
      );
    }
  });
}

export function retentionPolicyQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["audit-retention"],
    queryFn: () => unwrap(api.GET("/api/v1/audit/retention-policy"))
  });
}

/** All action types grouped by category, for the filter's multi-select. */
export function auditActionConfigQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["audit-action-config"],
    queryFn: async (): Promise<ActionConfig[]> => {
      const response = await unwrap(api.GET("/api/v1/audit/config/actions"));
      return response.actions;
    }
  });
}
