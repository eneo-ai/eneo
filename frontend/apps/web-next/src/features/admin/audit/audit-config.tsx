"use client";

import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { cn } from "@/lib/utils";
import {
  actionLabel,
  auditActionConfigQueryOptions,
  categoryLabel,
  type ActionType,
  type CategoryType
} from "./audit";

type CategoryConfig = Schema<"CategoryConfig">;
const CONFIG_KEY = ["audit-config"];
const ACTION_CONFIG_KEY = ["audit-action-config"];

export function auditConfigQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: CONFIG_KEY,
    queryFn: async (): Promise<CategoryConfig[]> => {
      const response = await unwrap(api.GET("/api/v1/audit/config"));
      return response.categories;
    }
  });
}

/**
 * Audit logging configuration: per-category toggles, each expandable to the
 * individual action types within it. Toggling a category sets all its actions
 * (backend cascades); toggling an action is independent. Both only affect new
 * events — history is never rewritten. Search filters the action list and
 * auto-expands the categories that match.
 */
export function AuditConfig() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { data: categories = [] } = useQuery(auditConfigQueryOptions(browserApi));
  const { data: actions = [] } = useQuery(auditActionConfigQueryOptions(browserApi));
  const [search, setSearch] = useState("");
  const [manuallyExpanded, setManuallyExpanded] = useState<Set<CategoryType>>(new Set());

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: CONFIG_KEY });
    queryClient.invalidateQueries({ queryKey: ACTION_CONFIG_KEY });
  };

  const toggleCategory = useMutation({
    mutationFn: (params: { category: CategoryType; enabled: boolean }) =>
      unwrap(
        browserApi.PATCH("/api/v1/audit/config", {
          body: { updates: [{ category: params.category, enabled: params.enabled }] }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const toggleAction = useMutation({
    mutationFn: (params: { action: ActionType; enabled: boolean }) =>
      unwrap(
        browserApi.PATCH("/api/v1/audit/config/actions", {
          body: { updates: [{ action: params.action, enabled: params.enabled }] }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const busy = toggleCategory.isPending || toggleAction.isPending;
  const query = search.trim().toLowerCase();

  const actionsByCategory = useMemo(() => {
    const map = new Map<CategoryType, { action: ActionType; enabled: boolean }[]>();
    for (const config of actions) {
      const matches =
        !query ||
        config.action.toLowerCase().includes(query) ||
        actionLabel(t, config.action).toLowerCase().includes(query);
      if (!matches) continue;
      const list = map.get(config.category) ?? [];
      list.push({ action: config.action, enabled: config.enabled });
      map.set(config.category, list);
    }
    return map;
  }, [actions, query, t]);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-muted-foreground text-sm">{t("audit_per_action_hint")}</p>
      <Input
        value={search}
        placeholder={t("search")}
        onChange={(event) => setSearch(event.target.value)}
        className="max-w-xs"
      />
      <div className="flex flex-col gap-2">
        {categories.map((category) => {
          const categoryActions = actionsByCategory.get(category.category) ?? [];
          // When searching, only categories with a matching action are shown,
          // and they are force-expanded so the matches are visible.
          if (query && categoryActions.length === 0) return null;
          const expanded = query.length > 0 || manuallyExpanded.has(category.category);
          const enabledCount = categoryActions.filter((item) => item.enabled).length;

          return (
            <div key={category.category} className="border-border rounded-lg border">
              <div className="flex items-center justify-between gap-4 p-4">
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  aria-expanded={expanded}
                  aria-label={expanded ? t("aria_collapse") : t("aria_expand")}
                  onClick={() =>
                    setManuallyExpanded((current) => {
                      const next = new Set(current);
                      if (next.has(category.category)) next.delete(category.category);
                      else next.add(category.category);
                      return next;
                    })
                  }
                >
                  <ChevronRight
                    aria-hidden="true"
                    className={cn(
                      "text-muted-foreground size-4 shrink-0 transition-transform",
                      expanded && "rotate-90"
                    )}
                  />
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="truncate font-medium">
                      {categoryLabel(t, category.category)}
                    </span>
                    <span className="text-muted-foreground text-xs">
                      {query
                        ? t("audit_actions_enabled_summary", {
                            enabled: enabledCount,
                            total: categoryActions.length
                          })
                        : t("audit_category_action_count", { count: category.action_count })}
                    </span>
                  </span>
                </button>
                <Switch
                  checked={category.enabled}
                  disabled={busy}
                  aria-label={categoryLabel(t, category.category)}
                  onCheckedChange={(enabled) =>
                    toggleCategory.mutate({ category: category.category, enabled })
                  }
                />
              </div>

              {expanded && categoryActions.length > 0 && (
                <ul className="border-border flex flex-col border-t">
                  {categoryActions.map((item) => (
                    <li key={item.action}>
                      <Label className="hover:bg-muted/40 flex items-center justify-between gap-4 px-4 py-2.5 pl-10 font-normal">
                        <span className="truncate text-sm">{actionLabel(t, item.action)}</span>
                        <Switch
                          checked={item.enabled}
                          disabled={busy}
                          onCheckedChange={(enabled) =>
                            toggleAction.mutate({ action: item.action, enabled })
                          }
                        />
                      </Label>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
