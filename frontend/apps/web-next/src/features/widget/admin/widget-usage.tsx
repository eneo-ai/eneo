"use client";

import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useId } from "react";
import { Table } from "@/components/astryx/table";
import { browserApi } from "@/lib/api/browser";
import type { Widget } from "./autosave";
import { widgetUsageQueryOptions } from "./queries";

/** Daily usage of a widget and how much of today's token budget is spent. */
export function WidgetUsage({ widget, visible = true }: { widget: Widget; visible?: boolean }) {
  const t = useTranslations();
  const locale = useLocale();
  const titleId = useId();
  const intlLocale = locale === "sv" ? "sv-SE" : "en-US";
  const number = new Intl.NumberFormat(intlLocale);
  const day = new Intl.DateTimeFormat(intlLocale, {
    weekday: "short",
    day: "numeric",
    month: "short"
  });

  // The budget in force is the server's (the policy may cap it), so a saved
  // change is fetched again rather than shown from the widget: the key
  // changes with every save, and the card is fetched afresh when it comes
  // into view.
  const usage = useQuery({
    ...widgetUsageQueryOptions(browserApi, widget.id, 14),
    queryKey: [
      ...widgetUsageQueryOptions(browserApi, widget.id, 14).queryKey,
      widget.limits.daily_token_budget ?? 0,
      widget.updated_at
    ],
    enabled: visible,
    staleTime: 0
  });

  const data = usage.data;
  const budgetPercent =
    data && data.daily_token_budget > 0
      ? Math.min(100, Math.round((data.budget_used_today / data.daily_token_budget) * 100))
      : 0;
  const days = data ? [...data.days].reverse() : [];
  const totals = days.reduce(
    (sum, row) => ({
      questions: sum.questions + row.questions,
      blocked: sum.blocked + row.blocked_budget + row.blocked_rate,
      helpful: sum.helpful + row.helpful,
      unhelpful: sum.unhelpful + row.unhelpful
    }),
    { questions: 0, blocked: 0, helpful: 0, unhelpful: 0 }
  );

  type Row = {
    id: string;
    day: string;
    questions: string;
    in: string;
    out: string;
    blocked: string;
    helpful: string;
    unhelpful: string;
  } & Record<string, unknown>;
  const rows: Row[] = days.map((row) => ({
    id: row.day,
    day: day.format(new Date(row.day)),
    questions: number.format(row.questions),
    in: number.format(row.input_tokens),
    out: number.format(row.output_tokens),
    blocked: number.format(row.blocked_budget + row.blocked_rate),
    helpful: number.format(row.helpful),
    unhelpful: number.format(row.unhelpful)
  }));
  const columns = [
    { key: "day", header: t("widget_admin_usage_day") },
    { key: "questions", header: t("widget_admin_usage_questions"), align: "end" as const },
    { key: "in", header: t("widget_admin_usage_tokens_in"), align: "end" as const },
    { key: "out", header: t("widget_admin_usage_tokens_out"), align: "end" as const },
    { key: "blocked", header: t("widget_admin_usage_blocked"), align: "end" as const },
    { key: "helpful", header: t("widget_admin_usage_helpful"), align: "end" as const },
    { key: "unhelpful", header: t("widget_admin_usage_unhelpful"), align: "end" as const }
  ];

  return (
    <section
      aria-labelledby={titleId}
      className="bg-ax-card border-ax-border flex flex-col gap-3 rounded-xl border p-4"
    >
      <h2 id={titleId} className="text-base font-semibold">
        {t("widget_admin_usage")}
      </h2>

      {usage.isError ? (
        <p role="alert" className="text-ax-red text-sm">
          {t("widget_admin_usage_failed")}
        </p>
      ) : !data ? (
        <p className="text-ax-text-secondary text-sm">{t("loading")}</p>
      ) : (
        <>
          <ProgressBar
            label={t("widget_admin_budget_today")}
            value={budgetPercent}
            max={100}
            variant={budgetPercent >= 90 ? "error" : "accent"}
            hasValueLabel
            formatValueLabel={() =>
              t("widget_admin_budget_used", {
                used: number.format(data.budget_used_today),
                budget: number.format(data.daily_token_budget)
              })
            }
          />

          {days.length === 0 ? (
            <p className="text-ax-text-secondary text-sm">{t("widget_admin_usage_empty")}</p>
          ) : (
            <>
              <Table<Row>
                aria-label={t("widget_admin_usage_caption")}
                data={rows}
                columns={columns}
                idKey="id"
                density="compact"
              />
              <p className="text-ax-text-secondary text-sm">
                {t("widget_admin_usage_totals", {
                  questions:
                    totals.questions === 1
                      ? t("widget_admin_usage_questions_total_one")
                      : t("widget_admin_usage_questions_total", {
                          count: number.format(totals.questions)
                        }),
                  blocked:
                    totals.blocked === 1
                      ? t("widget_admin_usage_blocked_total_one")
                      : t("widget_admin_usage_blocked_total", {
                          count: number.format(totals.blocked)
                        })
                })}{" "}
                {t("widget_admin_usage_feedback_totals", {
                  helpful: number.format(totals.helpful),
                  unhelpful:
                    totals.unhelpful === 1
                      ? t("widget_admin_usage_unhelpful_total_one")
                      : t("widget_admin_usage_unhelpful_total", {
                          count: number.format(totals.unhelpful)
                        })
                })}
              </p>
            </>
          )}
        </>
      )}
    </section>
  );
}
