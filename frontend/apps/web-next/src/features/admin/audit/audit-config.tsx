"use client";

import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { categoryLabel, type CategoryType } from "./audit";

type CategoryConfig = Schema<"CategoryConfig">;
const CONFIG_KEY = ["audit-config"];

export function auditConfigQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: CONFIG_KEY,
    queryFn: async (): Promise<CategoryConfig[]> => {
      const response = await unwrap(api.GET("/api/v1/audit/config"));
      return response.categories;
    }
  });
}

/** Per-category audit logging toggles (new events only; history is unaffected). */
export function AuditConfig() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { data: categories = [] } = useQuery(auditConfigQueryOptions(browserApi));

  const toggle = useMutation({
    mutationFn: (params: { category: CategoryType; enabled: boolean }) =>
      unwrap(
        browserApi.PATCH("/api/v1/audit/config", {
          body: { updates: [{ category: params.category, enabled: params.enabled }] }
        })
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CONFIG_KEY }),
    onError: (error) => toastApiError(error, t)
  });

  return (
    <div className="flex flex-col gap-4">
      <p className="text-muted-foreground text-sm">{t("audit_categories_hint")}</p>
      <div className="flex flex-col gap-2">
        {categories.map((category) => (
          <Label
            key={category.category}
            className="border-border flex items-center justify-between gap-4 rounded-lg border p-4 font-normal"
          >
            <span className="flex flex-col gap-0.5">
              <span className="font-medium">{categoryLabel(t, category.category)}</span>
              <span className="text-muted-foreground text-xs">
                {t("audit_category_action_count", { count: category.action_count })}
              </span>
            </span>
            <Switch
              checked={category.enabled}
              disabled={toggle.isPending}
              onCheckedChange={(enabled) => toggle.mutate({ category: category.category, enabled })}
            />
          </Label>
        ))}
      </div>
    </div>
  );
}
