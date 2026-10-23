"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useSettingSwitch } from "@/features/admin/use-setting-switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import {
  AUDIT_ACTION_CONFIG_KEY,
  AUDIT_CONFIG_KEY,
  actionLabel,
  auditActionConfigQueryOptions,
  auditConfigQueryOptions,
  categoryLabel,
  type ActionType,
  type CategoryType
} from "./audit";

// Category and action saves share one queue: a category cascades to its
// actions, so its save and an action's must not overtake each other.
const AUDIT_QUEUE = "audit-config";

/** A category's switch: saves on toggle and keeps focus while it saves. */
function CategorySwitch({
  category,
  enabled,
  label,
  onSaved
}: {
  category: CategoryType;
  enabled: boolean;
  label: string;
  onSaved: () => void;
}) {
  const [value, setValue, saving] = useSettingSwitch(
    `audit-category:${category}`,
    enabled,
    (next) =>
      unwrap(
        browserApi.PATCH("/api/v1/audit/config", {
          body: { updates: [{ category, enabled: next }] }
        })
      ),
    { onSaved, queue: AUDIT_QUEUE }
  );
  return (
    <Switch
      checked={value}
      aria-busy={saving || undefined}
      aria-label={label}
      onCheckedChange={setValue}
    />
  );
}

/** An action's switch, labelled by the row it sits in: saves on toggle and keeps focus. */
function ActionSwitch({
  action,
  enabled,
  onSaved
}: {
  action: ActionType;
  enabled: boolean;
  onSaved: () => void;
}) {
  const [value, setValue, saving] = useSettingSwitch(
    `audit-action:${action}`,
    enabled,
    (next) =>
      unwrap(
        browserApi.PATCH("/api/v1/audit/config/actions", {
          body: { updates: [{ action, enabled: next }] }
        })
      ),
    { onSaved, queue: AUDIT_QUEUE }
  );
  return <Switch checked={value} aria-busy={saving || undefined} onCheckedChange={setValue} />;
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
    void queryClient.invalidateQueries({ queryKey: AUDIT_CONFIG_KEY });
    void queryClient.invalidateQueries({ queryKey: AUDIT_ACTION_CONFIG_KEY });
  };

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
                <CategorySwitch
                  category={category.category}
                  enabled={category.enabled}
                  label={categoryLabel(t, category.category)}
                  onSaved={invalidate}
                />
              </div>

              {expanded && categoryActions.length > 0 && (
                <ul className="border-border flex flex-col border-t">
                  {categoryActions.map((item) => (
                    <li key={item.action}>
                      <Label className="hover:bg-muted/40 flex items-center justify-between gap-4 px-4 py-2.5 pl-10 font-normal">
                        <span className="truncate text-sm">{actionLabel(t, item.action)}</span>
                        <ActionSwitch
                          action={item.action}
                          enabled={item.enabled}
                          onSaved={invalidate}
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
