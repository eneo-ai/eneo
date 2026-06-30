"use client";

import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useId, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { PageHeader } from "@/components/composites/page-header";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { browserApi } from "@/lib/api/browser";
import {
  type InsightsRange,
  insightActivityQueryOptions,
  insightAggregatedQueryOptions,
  insightCountsQueryOptions,
  mergeInsightSeries
} from "@/features/admin/insights/insights";

const NUMBER = new Intl.NumberFormat("sv-SE");
const PRESET_DAYS = [7, 30, 90] as const;

function presetRange(days: number): InsightsRange {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - days);
  return { start: start.toISOString(), end: end.toISOString() };
}

/** The window of equal length immediately preceding `range` (for comparison). */
function priorRange(range: InsightsRange): InsightsRange {
  const start = new Date(range.start).getTime();
  const end = new Date(range.end).getTime();
  const duration = end - start;
  return { start: new Date(start - duration).toISOString(), end: range.start };
}

const toDateInput = (iso: string) => new Date(iso).toISOString().slice(0, 10);

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="flex flex-col gap-1 p-6">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="text-3xl font-semibold tabular-nums">{value}</span>
    </Card>
  );
}

const SERIES = [
  { key: "sessions", color: "var(--chart-1)", labelKey: "conversations_started" },
  { key: "questions", color: "var(--chart-2)", labelKey: "questions_asked" },
  { key: "assistants", color: "var(--chart-3)", labelKey: "assistants_created" }
] as const;

function UsageChart({ range }: { range: InsightsRange }) {
  const t = useTranslations();
  const locale = useLocale();
  const descriptionId = useId();

  const { data, isPending } = useQuery(insightAggregatedQueryOptions(browserApi, range));
  const series = useMemo(() => (data ? mergeInsightSeries(data) : []), [data]);

  const dateFmt = useMemo(
    () =>
      new Intl.DateTimeFormat(locale === "sv" ? "sv-SE" : "en-US", {
        month: "short",
        day: "numeric"
      }),
    [locale]
  );
  const formatDay = (value: string) => dateFmt.format(new Date(`${value}T00:00:00`));

  if (isPending) return <Skeleton className="h-[320px] w-full" />;
  if (series.length === 0) {
    return (
      <div className="text-muted-foreground flex h-[320px] items-center justify-center text-sm">
        {t("no_usage_data")}
      </div>
    );
  }

  return (
    <figure aria-describedby={descriptionId}>
      <p id={descriptionId} className="sr-only">
        {t("assistant_usage_description")}
      </p>
      <ResponsiveContainer width="100%" height={320}>
        <AreaChart data={series} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <defs>
            {SERIES.map((s) => (
              <linearGradient key={s.key} id={`fill-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={s.color} stopOpacity={0.3} />
                <stop offset="100%" stopColor={s.color} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatDay}
            tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            minTickGap={24}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            width={48}
          />
          <Tooltip
            labelFormatter={(label) => formatDay(String(label))}
            formatter={(value, name) => [NUMBER.format(Number(value)), name]}
            contentStyle={{
              background: "var(--popover)",
              border: "1px solid var(--border)",
              borderRadius: "0.5rem",
              color: "var(--popover-foreground)",
              fontSize: "0.8125rem"
            }}
          />
          <Legend wrapperStyle={{ fontSize: "0.8125rem" }} />
          {SERIES.map((s) => (
            <Area
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={t(s.labelKey)}
              stroke={s.color}
              fill={`url(#fill-${s.key})`}
              strokeWidth={2}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
      <table className="sr-only">
        <caption>{t("assistant_usage")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("migration_history_date")}</th>
            {SERIES.map((s) => (
              <th key={s.key} scope="col">
                {t(s.labelKey)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {series.map((point) => (
            <tr key={point.date}>
              <th scope="row">{formatDay(point.date)}</th>
              {SERIES.map((s) => (
                <td key={s.key}>{NUMBER.format(Number(point[s.key] ?? 0))}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

function Delta({ current, prior }: { current: number; prior?: number }) {
  if (prior == null) return null;
  const diff = current - prior;
  if (diff === 0) return <span className="text-muted-foreground text-xs">±0</span>;
  const up = diff > 0;
  return (
    <span
      className={
        up ? "text-xs text-green-700 dark:text-green-400" : "text-xs text-red-700 dark:text-red-400"
      }
    >
      {up ? "▲" : "▼"} {NUMBER.format(Math.abs(diff))}
    </span>
  );
}

function ActivityCards({ range, compare }: { range: InsightsRange; compare: boolean }) {
  const t = useTranslations();
  const { data } = useQuery(insightActivityQueryOptions(browserApi, range));
  const prior = useQuery({
    ...insightActivityQueryOptions(browserApi, priorRange(range)),
    enabled: compare
  });
  if (!data) return null;
  const priorData = compare ? prior.data : undefined;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <Card className="flex flex-col gap-1 p-6">
        <span className="text-muted-foreground text-sm">{t("active_assistants")}</span>
        <span className="flex items-baseline gap-2">
          <span className="text-3xl font-semibold tabular-nums">
            {NUMBER.format(data.active_assistant_count)} /{" "}
            {NUMBER.format(data.total_trackable_assistants)}
          </span>
          <Delta current={data.active_assistant_count} prior={priorData?.active_assistant_count} />
        </span>
      </Card>
      <Card className="flex flex-col gap-1 p-6">
        <span className="text-muted-foreground text-sm">{t("active_users")}</span>
        <span className="flex items-baseline gap-2">
          <span className="text-3xl font-semibold tabular-nums">
            {NUMBER.format(data.active_user_count)}
          </span>
          <Delta current={data.active_user_count} prior={priorData?.active_user_count} />
        </span>
      </Card>
      <Stat label={t("total_assistants")} value={NUMBER.format(data.total_trackable_assistants)} />
    </div>
  );
}

/**
 * Organization insights: headline totals, a usage time-series over a selectable
 * window (conversations / questions / assistants per day), and active-assistant
 * / active-user activity for the same window.
 */
export function InsightsPage() {
  const t = useTranslations();
  const { data: counts } = useSuspenseQuery(insightCountsQueryOptions(browserApi));
  const [range, setRange] = useState<InsightsRange>(() => presetRange(30));
  const [compare, setCompare] = useState(false);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("insights")} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label={t("assistants")} value={NUMBER.format(counts.assistants)} />
        <Stat label={t("sessions")} value={NUMBER.format(counts.sessions)} />
        <Stat label={t("questions")} value={NUMBER.format(counts.questions)} />
      </div>

      <Card className="flex flex-col gap-4 p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-0.5">
            <h2 className="font-semibold">{t("assistant_usage")}</h2>
            <p className="text-muted-foreground text-sm">{t("assistant_usage_description")}</p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex gap-1" role="group" aria-label={t("timeframe")}>
              {PRESET_DAYS.map((preset) => (
                <Button
                  key={preset}
                  size="sm"
                  variant="outline"
                  onClick={() => setRange(presetRange(preset))}
                >
                  {t(`last_${preset}_days`)}
                </Button>
              ))}
            </div>
            <label className="flex flex-col gap-1 text-xs">
              {t("from")}
              <Input
                type="date"
                className="h-8 w-36"
                value={toDateInput(range.start)}
                onChange={(event) =>
                  event.target.value &&
                  setRange((current) => ({
                    ...current,
                    start: new Date(`${event.target.value}T00:00:00`).toISOString()
                  }))
                }
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              {t("to")}
              <Input
                type="date"
                className="h-8 w-36"
                value={toDateInput(range.end)}
                onChange={(event) =>
                  event.target.value &&
                  setRange((current) => ({
                    ...current,
                    end: new Date(`${event.target.value}T23:59:59`).toISOString()
                  }))
                }
              />
            </label>
            <Button
              size="sm"
              variant={compare ? "default" : "outline"}
              aria-pressed={compare}
              onClick={() => setCompare((value) => !value)}
            >
              {t("compare")}
            </Button>
          </div>
        </div>
        <UsageChart range={range} />
      </Card>

      <div className="flex flex-col gap-3">
        <h2 className="font-semibold">{t("insights_assistant_activity")}</h2>
        <ActivityCards range={range} compare={compare} />
      </div>
    </div>
  );
}
