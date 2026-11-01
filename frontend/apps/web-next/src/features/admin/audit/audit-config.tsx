"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { LeaveConfirmation } from "@/components/composites/leave-confirmation";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { Switch } from "@/components/ui/switch";
import { useSettingSwitch } from "@/features/admin/use-setting-switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { matchesSearch } from "@/lib/search";
import { cn } from "@/lib/utils";
import {
  AUDIT_ACTION_CONFIG_KEY,
  AUDIT_CONFIG_KEY,
  actionLabel,
  auditActionConfigQueryOptions,
  auditConfigQueryOptions,
  categoryLabel,
  type ActionConfig,
  type ActionType,
  type CategoryConfig,
  type CategoryType
} from "./audit";

// The API-key settings page still uses the immediate action switch.
const AUDIT_QUEUE = "audit-config";

/** An action's switch, labelled by the row it sits in: saves on toggle and keeps focus. */
export function ActionSwitch({
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

type ConfigDraft = {
  categories: Partial<Record<CategoryType, boolean>>;
  actions: Partial<Record<ActionType, boolean>>;
};
type ConfigUpdates = {
  categories: Pick<CategoryConfig, "category" | "enabled">[];
  actions: Pick<ActionConfig, "action" | "enabled">[];
};

/** Stages category and action settings behind one explicit Save operation. */
export function AuditConfig() {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const id = useId();
  const [draft, setDraft] = useState<ConfigDraft | null>(null);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<CategoryType>>(new Set());
  const [partial, setPartial] = useState(false);
  const [baselineKnown, setBaselineKnown] = useState(true);
  const [reconciling, setReconciling] = useState(false);

  async function refreshBaseline() {
    setReconciling(true);
    // A category response cannot tell us the effective actions: overrides win.
    const results = await Promise.allSettled([
      queryClient.query({ ...auditConfigQueryOptions(browserApi), staleTime: 0, retry: false }),
      queryClient.query({
        ...auditActionConfigQueryOptions(browserApi),
        staleTime: 0,
        retry: false
      })
    ]);
    const known = results.every((result) => result.status === "fulfilled");
    setBaselineKnown(known);
    setReconciling(false);
    return known;
  }

  const save = useMutation({
    mutationFn: async (updates: ConfigUpdates) => {
      setPartial(false);
      await Promise.all([
        queryClient.cancelQueries({ queryKey: AUDIT_CONFIG_KEY }),
        queryClient.cancelQueries({ queryKey: AUDIT_ACTION_CONFIG_KEY })
      ]);
      let categorySaved = false;
      try {
        if (updates.categories.length) {
          const response = await unwrap(
            browserApi.PATCH("/api/v1/audit/config", {
              body: { updates: updates.categories }
            })
          );
          queryClient.setQueryData(AUDIT_CONFIG_KEY, response.categories);
          categorySaved = true;
        }
        if (updates.actions.length) {
          const response = await unwrap(
            browserApi.PATCH("/api/v1/audit/config/actions", {
              body: { updates: updates.actions }
            })
          );
          queryClient.setQueryData(AUDIT_ACTION_CONFIG_KEY, response.actions);
        }
      } catch (error) {
        setPartial(categorySaved);
        setBaselineKnown(false);
        // Keep the user's draft. Reset/retry needs confirmed effective server values,
        // including a request that may have committed before its response was lost.
        await refreshBaseline();
        throw error;
      }
    },
    onSuccess: () => {
      setDraft(null);
      setBaselineKnown(true);
      announce(t("audit_config_saved"));
    }
  });
  const busy = save.isPending || reconciling;
  const categoryQuery = useQuery({
    ...auditConfigQueryOptions(browserApi),
    refetchOnWindowFocus: !busy,
    refetchOnReconnect: !busy
  });
  const actionQuery = useQuery({
    ...auditActionConfigQueryOptions(browserApi),
    refetchOnWindowFocus: !busy,
    refetchOnReconnect: !busy
  });
  const actual = {
    categories: categoryQuery.data ?? [],
    actions: actionQuery.data ?? []
  };
  const shown = {
    categories: actual.categories.map((item) => ({
      ...item,
      enabled: draft?.categories[item.category] ?? item.enabled
    })),
    actions: actual.actions.map((item) => ({
      ...item,
      enabled: draft?.actions[item.action] ?? item.enabled
    }))
  };
  const categoryUpdates = shown.categories.filter(
    (item) =>
      actual.categories.find((saved) => saved.category === item.category)?.enabled !== item.enabled
  );
  const changedCategories = new Set(categoryUpdates.map((item) => item.category));
  const actionUpdates = shown.actions.filter(
    (item) =>
      changedCategories.has(item.category) ||
      actual.actions.find((saved) => saved.action === item.action)?.enabled !== item.enabled
  );
  const dirty = categoryUpdates.length > 0 || actionUpdates.length > 0;
  const unsaved = dirty || (!baselineKnown && draft !== null);

  function stage(next: ConfigDraft) {
    const changed =
      actual.categories.some(
        (item) =>
          next.categories[item.category] !== undefined &&
          next.categories[item.category] !== item.enabled
      ) ||
      actual.actions.some(
        (item) =>
          next.actions[item.action] !== undefined && next.actions[item.action] !== item.enabled
      );
    setDraft(changed ? next : null);
  }
  function toggleCategory(category: CategoryType, enabled: boolean) {
    stage({
      categories: { ...draft?.categories, [category]: enabled },
      actions: {
        ...draft?.actions,
        ...Object.fromEntries(
          actual.actions
            .filter((item) => item.category === category)
            .map((item) => [item.action, enabled])
        )
      }
    });
  }
  function toggleAction(action: ActionConfig, enabled: boolean) {
    const siblings = shown.actions
      .filter((item) => item.category === action.category)
      .map((item) => (item.action === action.action ? { ...item, enabled } : item));
    const allEnabled = siblings.every((item) => item.enabled);
    const allDisabled = siblings.every((item) => !item.enabled);
    stage({
      actions: { ...draft?.actions, [action.action]: enabled },
      categories: {
        ...draft?.categories,
        ...(allEnabled || allDisabled ? { [action.category]: allEnabled } : {})
      }
    });
  }
  function reset() {
    if (busy || !baselineKnown) return;
    setDraft(null);
    setPartial(false);
    save.reset();
  }

  return (
    <QueryStateBoundary
      queries={[
        { ...categoryQuery, refetch: refreshBaseline },
        { ...actionQuery, refetch: refreshBaseline }
      ]}
      rows={5}
    >
      {() => (
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!dirty || busy || !baselineKnown) return;
            save.mutate({
              categories: categoryUpdates.map(({ category, enabled }) => ({ category, enabled })),
              actions: actionUpdates.map(({ action, enabled }) => ({ action, enabled }))
            });
          }}
        >
          <LeaveConfirmation active={unsaved || save.isPending} />
          <p className="text-ax-text-secondary text-sm">{t("audit_config_description")}</p>
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-0 flex-1 basis-56">
              <TextInput
                label={t("search")}
                value={search}
                onChange={setSearch}
                hasClear
                width="100%"
              />
            </div>
            <Button
              label={t("audit_config_expand_all")}
              onClick={() => setExpanded(new Set(shown.categories.map((item) => item.category)))}
            />
            <Button
              label={t("audit_config_collapse_all")}
              onClick={() => {
                setSearch("");
                setExpanded(new Set());
              }}
            />
          </div>
          <div className="flex flex-col gap-3">
            {shown.categories.map((category) => {
              const allActions = shown.actions.filter(
                (item) => item.category === category.category
              );
              const categoryMatches = matchesSearch(
                [
                  categoryLabel(t, category.category),
                  t(`audit_category_${category.category}_description`)
                ],
                search
              );
              const actions = allActions.filter(
                (item) =>
                  categoryMatches ||
                  matchesSearch(
                    [
                      item.action,
                      actionLabel(t, item.action),
                      t.has(`audit_action_${item.action}_description`)
                        ? t(`audit_action_${item.action}_description`)
                        : ""
                    ],
                    search
                  )
              );
              if (search.trim() && !actions.length) return null;
              const isExpanded = !!search.trim() || expanded.has(category.category);
              const regionId = `${id}-${category.category}`;
              return (
                <section
                  key={category.category}
                  className="border-ax-border rounded-ax-container border"
                >
                  <div className="flex items-start justify-between gap-3 p-4">
                    <div className="min-w-0 flex-1">
                      <h2 className="text-base font-semibold">
                        <button
                          type="button"
                          aria-expanded={isExpanded}
                          aria-controls={regionId}
                          className="focus-visible:outline-ring rounded-ax-inner flex min-h-11 items-center gap-2 text-start focus-visible:outline-2 focus-visible:outline-offset-2"
                          onClick={() =>
                            setExpanded((current) => {
                              const next = new Set(current);
                              if (next.has(category.category)) next.delete(category.category);
                              else next.add(category.category);
                              return next;
                            })
                          }
                        >
                          <ChevronRight
                            aria-hidden="true"
                            className={cn("size-4 shrink-0", isExpanded && "rotate-90")}
                          />
                          {categoryLabel(t, category.category)}
                        </button>
                      </h2>
                      <p className="text-ax-text-secondary text-sm">
                        {t(`audit_category_${category.category}_description`)}
                      </p>
                      <p className="text-ax-text-secondary mt-1 text-xs">
                        {t("audit_actions_enabled_summary", {
                          enabled: allActions.filter((item) => item.enabled).length,
                          total: allActions.length
                        })}
                      </p>
                    </div>
                    <CheckboxInput
                      label={categoryLabel(t, category.category)}
                      isLabelHidden
                      value={category.enabled}
                      isDisabled={busy || !baselineKnown}
                      onChange={(enabled) => toggleCategory(category.category, enabled)}
                    />
                  </div>
                  <div id={regionId} hidden={!isExpanded}>
                    {isExpanded ? (
                      <ul className="border-ax-border flex flex-col gap-3 border-t p-4">
                        {actions.map((item) => (
                          <li key={item.action} className="flex items-start justify-between gap-3">
                            <CheckboxInput
                              label={actionLabel(t, item.action)}
                              value={item.enabled}
                              description={
                                t.has(`audit_action_${item.action}_description`)
                                  ? t(`audit_action_${item.action}_description`)
                                  : undefined
                              }
                              isDisabled={busy || !baselineKnown}
                              onChange={(enabled) => toggleAction(item, enabled)}
                            />
                            {!item.enabled ? (
                              <span className="text-ax-text-secondary shrink-0 text-xs">
                                {t("audit_config_disabled")}
                              </span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </section>
              );
            })}
          </div>
          {save.isError ? (
            <ListError
              error={save.error}
              title={t(partial ? "audit_config_partial_save" : "audit_config_save_failed")}
            />
          ) : null}
          {!baselineKnown ? (
            <div className="flex flex-col items-start gap-2">
              <p className="text-ax-text-secondary text-sm">{t("audit_config_server_unknown")}</p>
              <Button
                label={t("audit_config_reload_server")}
                isLoading={reconciling}
                isInterruptible
                onClick={() => {
                  if (!busy) void refreshBaseline();
                }}
              />
            </div>
          ) : null}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-ax-text-secondary text-sm">
              {unsaved ? t("audit_config_unsaved_changes") : t("audit_per_action_hint")}
            </p>
            <div className="flex gap-2">
              <Button
                label={t("audit_config_reset")}
                isDisabled={!dirty || !baselineKnown}
                aria-disabled={busy || !dirty || !baselineKnown}
                onClick={reset}
              />
              <Button
                type="submit"
                variant="primary"
                label={t("audit_config_save")}
                isLoading={save.isPending}
                isInterruptible
                isDisabled={!baselineKnown}
                tooltip={!baselineKnown ? t("audit_config_server_unknown") : undefined}
              />
            </div>
          </div>
        </form>
      )}
    </QueryStateBoundary>
  );
}
