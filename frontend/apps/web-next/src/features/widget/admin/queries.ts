import { queryOptions } from "@tanstack/react-query";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type Widget = Schema<"WidgetPublic">;
export type WidgetUpdate = Schema<"WidgetUpdate">;
export type WidgetPolicy = Schema<"WidgetPolicyPublic">;
export type WidgetTemplate = Schema<"WidgetTemplatePublic">;
export type WidgetUsage = Schema<"WidgetUsagePublic">;
export type WidgetPreviewToken = Schema<"WidgetPreviewToken">;

/** The widgets configured in a space (the widgets permission). */
export function spaceWidgetsQueryOptions(api: EneoClient, spaceId: string) {
  return queryOptions({
    queryKey: ["spaces", spaceId, "widgets"],
    queryFn: (): Promise<Widget[]> =>
      unwrap(
        api.GET("/api/v1/spaces/{space_id}/widgets/", { params: { path: { space_id: spaceId } } })
      ).then((page) => page.items)
  });
}

/**
 * The organisation's limits for widgets. Readable with the widgets
 * permission, so every editor checks limits against the same bounds the
 * server enforces; null when the backend refuses it.
 */
export function widgetPolicyQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["widget-policy"],
    queryFn: (): Promise<WidgetPolicy | null> =>
      unwrap(api.GET("/api/v1/admin/widget-policy/")).catch(() => null)
  });
}

/** The organisation's templates, default first; empty when the backend refuses them. */
export function widgetTemplatesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["widget-templates"],
    queryFn: (): Promise<WidgetTemplate[]> =>
      unwrap(api.GET("/api/v1/widget-templates/"))
        .then((page) => page.items)
        .catch(() => [])
  });
}

export function widgetUsageQueryOptions(api: EneoClient, widgetId: string, days: number) {
  return queryOptions({
    queryKey: ["widgets", widgetId, "usage", days],
    queryFn: (): Promise<WidgetUsage> =>
      unwrap(
        api.GET("/api/v1/widgets/{id}/usage/", {
          params: { path: { id: widgetId }, query: { days } }
        })
      )
  });
}

/** Whether an active web widget publishes the assistant (anyone who can read it may ask). */
export function assistantWidgetStatusQueryOptions(api: EneoClient, assistantId: string) {
  return queryOptions({
    queryKey: ["assistants", assistantId, "widget-status"],
    queryFn: (): Promise<{ serves_active_widget: boolean }> =>
      unwrap(
        api.GET("/api/v1/assistants/{id}/widget-status/", {
          params: { path: { id: assistantId } }
        })
      )
  });
}

/** The admin side of one widget, as the editor drives it. */
export const widgetApi = {
  get: (id: string): Promise<Widget> =>
    unwrap(browserApi.GET("/api/v1/widgets/{id}/", { params: { path: { id } } })),
  create: (spaceId: string, body: Schema<"WidgetCreate">): Promise<Widget> =>
    unwrap(
      browserApi.POST("/api/v1/spaces/{space_id}/widgets/", {
        params: { path: { space_id: spaceId } },
        body
      })
    ),
  /** Partial update; visitor-facing changes bump the token generation. */
  update: (id: string, body: WidgetUpdate): Promise<Widget> =>
    unwrap(browserApi.PATCH("/api/v1/widgets/{id}/", { params: { path: { id } }, body })),
  activate: (id: string): Promise<Widget> =>
    unwrap(browserApi.POST("/api/v1/widgets/{id}/activate/", { params: { path: { id } } })),
  /** The kill switch: takes effect immediately for every visitor. */
  pause: (id: string): Promise<Widget> =>
    unwrap(browserApi.POST("/api/v1/widgets/{id}/pause/", { params: { path: { id } } })),
  archive: (id: string): Promise<Widget> =>
    unwrap(browserApi.POST("/api/v1/widgets/{id}/archive/", { params: { path: { id } } })),
  /** Token that lets the admin page frame the real embed page of a draft or paused widget. */
  previewToken: (id: string): Promise<WidgetPreviewToken> =>
    unwrap(browserApi.POST("/api/v1/widgets/{id}/preview-token/", { params: { path: { id } } })),
  linkTemplate: (id: string, templateId: string, revision: number): Promise<Widget> =>
    unwrap(
      browserApi.POST("/api/v1/widgets/{id}/link-template/", {
        params: { path: { id } },
        body: { template_id: templateId, revision }
      })
    ),
  detachTemplate: (id: string, revision: number): Promise<Widget> =>
    unwrap(
      browserApi.POST("/api/v1/widgets/{id}/detach-template/", {
        params: { path: { id } },
        body: { revision }
      })
    )
};
