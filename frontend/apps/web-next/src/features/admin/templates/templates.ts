import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type AssistantTemplate = Schema<"AssistantTemplateAdminPublic">;
export type AppTemplate = Schema<"AppTemplateAdminPublic">;
export type AssistantTemplateCreate = Schema<"AssistantTemplateAdminCreate">;
export type AssistantTemplateUpdate = Schema<"AssistantTemplateAdminUpdate">;
export type AppTemplateCreate = Schema<"AppTemplateAdminCreate">;
export type AppTemplateUpdate = Schema<"AppTemplateAdminUpdate">;

export const ASSISTANT_KEY = ["admin-templates", "assistants"];
export const APP_KEY = ["admin-templates", "apps"];
export const DELETED_ASSISTANT_KEY = ["admin-templates", "assistants", "deleted"];
export const DELETED_APP_KEY = ["admin-templates", "apps", "deleted"];

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

export function deletedAssistantTemplatesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: DELETED_ASSISTANT_KEY,
    queryFn: async (): Promise<AssistantTemplate[]> =>
      (await unwrap(api.GET("/api/v1/admin/templates/assistants/deleted"))).items
  });
}
export function deletedAppTemplatesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: DELETED_APP_KEY,
    queryFn: async (): Promise<AppTemplate[]> =>
      (await unwrap(api.GET("/api/v1/admin/templates/apps/deleted"))).items
  });
}

export function createAssistantTemplate(api: EneoClient, body: AssistantTemplateCreate) {
  return unwrap(api.POST("/api/v1/admin/templates/assistants/", { body }));
}
export function updateAssistantTemplate(
  api: EneoClient,
  templateId: string,
  body: AssistantTemplateUpdate
) {
  return unwrap(
    api.PATCH("/api/v1/admin/templates/assistants/{template_id}", {
      params: { path: { template_id: templateId } },
      body
    })
  );
}
export function createAppTemplate(api: EneoClient, body: AppTemplateCreate) {
  return unwrap(api.POST("/api/v1/admin/templates/apps/", { body }));
}
export function updateAppTemplate(api: EneoClient, templateId: string, body: AppTemplateUpdate) {
  return unwrap(
    api.PATCH("/api/v1/admin/templates/apps/{template_id}", {
      params: { path: { template_id: templateId } },
      body
    })
  );
}
