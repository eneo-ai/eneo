import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type AssistantTemplate = Schema<"AssistantTemplateAdminPublic">;
export type AppTemplate = Schema<"AppTemplateAdminPublic">;

export const ASSISTANT_KEY = ["admin-templates", "assistants"];
export const APP_KEY = ["admin-templates", "apps"];

export function assistantTemplatesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ASSISTANT_KEY,
    queryFn: async (): Promise<AssistantTemplate[]> => {
      const page = await unwrap(api.GET("/api/v1/admin/templates/assistants/"));
      return page.items.filter((item) => !item.deleted_at);
    }
  });
}
export function appTemplatesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: APP_KEY,
    queryFn: async (): Promise<AppTemplate[]> => {
      const page = await unwrap(api.GET("/api/v1/admin/templates/apps/"));
      return page.items.filter((item) => !item.deleted_at);
    }
  });
}
