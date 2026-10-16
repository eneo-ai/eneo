import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type TenantIntegration = Schema<"TenantIntegration">;
export type SharePointApp = Schema<"TenantSharePointAppPublic">;
export type SharePointSubscription = Schema<"SharePointSubscriptionPublic">;

export const TENANT_INTEGRATIONS_KEY = ["admin-tenant-integrations"];
export const SHAREPOINT_APP_KEY = ["admin-sharepoint-app"];
export const SHAREPOINT_SUBSCRIPTIONS_KEY = ["admin-sharepoint-subscriptions"];

export function tenantIntegrationsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: TENANT_INTEGRATIONS_KEY,
    queryFn: async (): Promise<TenantIntegration[]> => {
      const page = await unwrap(api.GET("/api/v1/integrations/tenant/"));
      return page.items;
    }
  });
}

/** The tenant's SharePoint Azure-AD app config (null when not configured). */
export function sharepointAppQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: SHAREPOINT_APP_KEY,
    queryFn: (): Promise<SharePointApp | null> => unwrap(api.GET("/api/v1/admin/sharepoint/app"))
  });
}

/** Webhook subscriptions for the tenant (with renewal-health fields). */
export function sharepointSubscriptionsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: SHAREPOINT_SUBSCRIPTIONS_KEY,
    queryFn: async (): Promise<SharePointSubscription[]> => {
      const result = await unwrap(api.GET("/api/v1/admin/sharepoint/subscriptions"));
      return Array.isArray(result) ? result : [];
    }
  });
}
