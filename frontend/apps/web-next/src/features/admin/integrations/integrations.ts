import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type TenantIntegration = Schema<"TenantIntegration">;

export const TENANT_INTEGRATIONS_KEY = ["admin-tenant-integrations"];

export function tenantIntegrationsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: TENANT_INTEGRATIONS_KEY,
    queryFn: async (): Promise<TenantIntegration[]> => {
      const page = await unwrap(api.GET("/api/v1/integrations/tenant/"));
      return page.items;
    }
  });
}
