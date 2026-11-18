import { queryOptions, type QueryClient } from "@tanstack/react-query";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { WidgetTemplate, WidgetTemplateUpdate } from "../autosave";
import { widgetTemplatesQueryOptions, type WidgetPolicy } from "../queries";

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

/** Keep the list and previously visited detail pages in sync with a server mutation. */
export function cacheWidgetTemplate(client: QueryClient, saved: WidgetTemplate) {
  const listKey = widgetTemplatesQueryOptions(browserApi).queryKey;
  const detailKey = widgetTemplateQueryOptions(browserApi, saved.id).queryKey;
  if (saved.is_default) {
    const details = client.getQueriesData<WidgetTemplate>({
      queryKey: listKey,
      predicate: ({ queryKey }) => queryKey.length === detailKey.length
    });
    for (const [key, template] of details) {
      if (template?.is_default && template.id !== saved.id) {
        client.setQueryData(key, { ...template, is_default: false });
      }
    }
  }
  client.setQueryData(detailKey, saved);
  client.setQueryData(listKey, (items) => {
    if (!items) return items;
    const rest = items
      .filter((item) => item.id !== saved.id)
      .map((item) => (saved.is_default && item.is_default ? { ...item, is_default: false } : item));
    return [...rest, saved].sort(
      (a, b) => Number(b.is_default) - Number(a.is_default) || a.name.localeCompare(b.name)
    );
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
