"use client";

import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Pause, Play } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { Switch } from "@/components/astryx/switch";
import { blockerLabel } from "../blockers";
import { toastWidgetError } from "../errors";
import { widgetApi } from "../queries";
import { WIDGET_OVERVIEW_KEY, type WidgetOverview, type WidgetOverviewItem } from "./queries";

/**
 * The organisation's widgets at a glance, one card each: where it lives,
 * whether it is serving visitors and how much it is used. Cards instead of a
 * wide table so nothing needs to scroll sideways and each widget reads as a
 * unit on any screen.
 */
export function WidgetOverviewList({ overview }: { overview: WidgetOverview }) {
  const t = useTranslations();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const onlyActiveId = useId();
  const intlLocale = locale === "sv" ? "sv-SE" : "en-US";
  const number = new Intl.NumberFormat(intlLocale);
  const day = new Intl.DateTimeFormat(intlLocale, { day: "numeric", month: "short" });

  // Pausing a live widget is the kill switch, so it asks first; resuming and
  // activating are safe to do straight away. The list is reloaded afterwards.
  const [toPause, setToPause] = useState<WidgetOverviewItem | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [onlyActive, setOnlyActive] = useState(false);

  async function run(item: WidgetOverviewItem, action: "pause" | "activate") {
    if (busyId) return;
    setBusyId(item.id);
    try {
      if (action === "pause") await widgetApi.pause(item.id);
      else await widgetApi.activate(item.id);
      setToPause(null);
      await queryClient.invalidateQueries({ queryKey: WIDGET_OVERVIEW_KEY });
    } catch (error) {
      toastWidgetError(error, t);
    } finally {
      setBusyId(null);
    }
  }

  const items = onlyActive
    ? overview.items.filter((item) => item.status === "active")
    : overview.items;

  const statusLabel = (item: WidgetOverviewItem) =>
    item.status === "active"
      ? t("widget_admin_status_active")
      : item.status === "paused"
        ? t("widget_admin_status_paused")
        : item.status === "archived"
          ? t("widget_admin_status_archived")
          : t("widget_admin_status_draft");
  const widgetHref = (item: WidgetOverviewItem) =>
    `/spaces/${item.space_id}/assistants/${item.target_id}/widget`;
  const blockedReason = (item: WidgetOverviewItem) =>
    (item.activation_blockers ?? []).map((code) => blockerLabel(code, t)).join(", ");
  const budgetPercent = (item: WidgetOverviewItem) =>
    item.daily_token_budget
      ? Math.min(100, Math.round((item.budget_used_today / item.daily_token_budget) * 100))
      : 0;

  if (overview.items.length === 0) {
    return <p className="text-ax-text-secondary text-sm">{t("widget_admin_overview_empty")}</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <Switch
          id={onlyActiveId}
          label={t("widget_admin_overview_only_active")}
          value={onlyActive}
          labelPosition="start"
          onChange={setOnlyActive}
        />
      </div>

      <ul className="grid gap-4 xl:grid-cols-2" aria-label={t("widget_admin_overview_caption")}>
        {items.map((item) => {
          const reason = blockedReason(item);
          const percent = budgetPercent(item);
          return (
            <li key={item.id}>
              <article className="bg-ax-card border-ax-border flex h-full flex-col gap-4 rounded-xl border p-4">
                <div className="border-ax-border flex flex-wrap items-start justify-between gap-2 border-b pb-3">
                  <div className="min-w-0">
                    <h3 className="flex flex-wrap items-center gap-2 text-base font-semibold">
                      <Link className="underline-offset-2 hover:underline" href={widgetHref(item)}>
                        {item.name}
                      </Link>
                      <Badge
                        variant={
                          item.status === "active"
                            ? "success"
                            : item.status === "paused"
                              ? "warning"
                              : "neutral"
                        }
                        label={statusLabel(item)}
                      />
                    </h3>
                    <p className="text-ax-text-secondary text-sm">
                      {item.space_name ?? "–"} · {item.assistant_name ?? "–"} ·{" "}
                      {item.allowed_origins.length === 1
                        ? t("widget_admin_overview_origins_one")
                        : t("widget_admin_overview_origins", {
                            count: number.format(item.allowed_origins.length)
                          })}
                    </p>
                  </div>
                  <Link
                    className="text-ax-accent inline-flex items-center gap-1 text-sm underline-offset-2 hover:underline"
                    href={widgetHref(item)}
                    aria-label={t("widget_admin_overview_open", { name: item.name })}
                  >
                    {t("widget_admin_open")}
                    <ArrowRight className="size-4" aria-hidden="true" />
                  </Link>
                </div>

                {item.status === "active" && reason && (
                  // Live, but not serving as configured: say so where the badge says "Aktiv".
                  <p className="bg-ax-orange-muted text-ax-orange rounded-lg px-3 py-2 text-sm">
                    {t("widget_admin_overview_active_issues", { reasons: reason })}
                  </p>
                )}

                <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-5">
                  <div>
                    <dt className="text-ax-text-secondary text-xs">
                      {t("widget_admin_overview_questions_7d")}
                    </dt>
                    <dd className="text-lg font-semibold tabular-nums">
                      {number.format(item.questions_7d)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ax-text-secondary text-xs">
                      {t("widget_admin_overview_questions_30d")}
                    </dt>
                    <dd className="text-lg font-semibold tabular-nums">
                      {number.format(item.questions_30d)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ax-text-secondary text-xs">
                      {t("widget_admin_overview_tokens_30d")}
                    </dt>
                    <dd className="text-lg font-semibold tabular-nums">
                      {number.format(item.input_tokens_30d + item.output_tokens_30d)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ax-text-secondary text-xs">
                      {t("widget_admin_overview_blocked_30d")}
                    </dt>
                    <dd
                      className={`text-lg font-semibold tabular-nums ${item.blocked_30d > 0 ? "text-ax-orange" : ""}`}
                    >
                      {number.format(item.blocked_30d)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ax-text-secondary text-xs">
                      {t("widget_admin_overview_feedback_30d")}
                    </dt>
                    <dd className="text-lg font-semibold tabular-nums">
                      {t("widget_admin_overview_feedback_value", {
                        helpful: number.format(item.helpful_30d),
                        unhelpful: number.format(item.unhelpful_30d)
                      })}
                    </dd>
                  </div>
                </dl>

                <ProgressBar
                  label={t("widget_admin_overview_budget_today")}
                  value={percent}
                  max={100}
                  variant={percent >= 90 ? "error" : "accent"}
                  hasValueLabel
                  formatValueLabel={() =>
                    item.status === "active"
                      ? t("widget_admin_budget_used", {
                          used: number.format(item.budget_used_today),
                          budget: number.format(item.daily_token_budget)
                        })
                      : t("widget_admin_overview_budget_inactive", {
                          budget: number.format(item.daily_token_budget)
                        })
                  }
                />

                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-ax-text-secondary text-xs">
                    {t("widget_admin_overview_last_activity")}:{" "}
                    {item.last_activity
                      ? day.format(new Date(item.last_activity))
                      : t("widget_admin_overview_never")}
                  </p>
                  {item.status !== "archived" && (
                    <div
                      role="group"
                      aria-label={t("widget_admin_overview_actions", { name: item.name })}
                      className="flex flex-col items-end gap-1"
                    >
                      {item.status === "active" ? (
                        <Button
                          size="sm"
                          label={t("widget_admin_pause")}
                          icon={<Pause aria-hidden="true" className="size-4" />}
                          onClick={() => setToPause(item)}
                        />
                      ) : (
                        <>
                          <Button
                            size="sm"
                            label={
                              item.status === "paused"
                                ? t("widget_admin_resume")
                                : t("widget_admin_activate")
                            }
                            icon={<Play aria-hidden="true" className="size-4" />}
                            isDisabled={reason !== ""}
                            tooltip={reason || undefined}
                            isLoading={busyId === item.id}
                            isInterruptible
                            clickAction={() => run(item, "activate")}
                          />
                          {reason && (
                            <p className="text-ax-orange text-xs">
                              {t("widget_admin_overview_blocked", { reasons: reason })}
                            </p>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              </article>
            </li>
          );
        })}
      </ul>

      <AlertDialog
        isOpen={toPause !== null}
        onOpenChange={(open) => {
          if (!open && !busyId) setToPause(null);
        }}
        title={t("widget_admin_overview_pause_title", { name: toPause?.name ?? "" })}
        description={t("widget_admin_overview_pause_description")}
        actionLabel={t("widget_admin_pause")}
        cancelLabel={t("cancel")}
        actionVariant="destructive"
        isActionLoading={busyId !== null}
        onAction={() => {
          if (toPause) void run(toPause, "pause");
        }}
      />
    </div>
  );
}
