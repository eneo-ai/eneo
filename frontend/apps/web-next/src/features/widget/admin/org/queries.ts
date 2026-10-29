import { queryOptions } from "@tanstack/react-query";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { WidgetTemplate, WidgetTemplateUpdate } from "../autosave";
import type { WidgetPolicy } from "../queries";

export type WidgetOverview = Schema<"WidgetOverviewPublic">;
export type WidgetOverviewItem = Schema<"WidgetOverviewItem">;
export type WidgetPolicyUpdate = Schema<"WidgetPolicyUpdate">;

export const WIDGET_OVERVIEW_KEY = ["admin", "widgets", "overview"] as const;

/** Every widget in the organisation with where it lives and its usage (tenant admins). */
export function widgetOverviewQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: WIDGET_OVERVIEW_KEY,
    queryFn: (): Promise<WidgetOverview> => unwrap(api.GET("/api/v1/admin/widgets/"))
  });
}

/** One template with its draft and release, as the admin editor needs it. */
export function widgetTemplateQueryOptions(api: EneoClient, templateId: string) {
  return queryOptions({
    queryKey: ["widget-templates", templateId],
    queryFn: (): Promise<WidgetTemplate> =>
      unwrap(
        api.GET("/api/v1/admin/widget-templates/{id}/", { params: { path: { id: templateId } } })
      )
  });
}

export const widgetPolicyApi = {
  update: (body: WidgetPolicyUpdate): Promise<WidgetPolicy> =>
    unwrap(browserApi.PATCH("/api/v1/admin/widget-policy/", { body }))
};

export const widgetTemplateApi = {
  create: (body: Schema<"WidgetTemplateCreate">): Promise<WidgetTemplate> =>
    unwrap(browserApi.POST("/api/v1/admin/widget-templates/", { body })),
  update: (id: string, body: WidgetTemplateUpdate): Promise<WidgetTemplate> =>
    unwrap(
      browserApi.PATCH("/api/v1/admin/widget-templates/{id}/", { params: { path: { id } }, body })
    ),
  /** Copies the draft onto every follower's locked parts; the deliberate step after saving. */
  publish: (id: string): Promise<WidgetTemplate> =>
    unwrap(
      browserApi.POST("/api/v1/admin/widget-templates/{id}/publish/", { params: { path: { id } } })
    ),
  delete: (id: string): Promise<unknown> =>
    unwrap(browserApi.DELETE("/api/v1/admin/widget-templates/{id}/", { params: { path: { id } } }))
};
