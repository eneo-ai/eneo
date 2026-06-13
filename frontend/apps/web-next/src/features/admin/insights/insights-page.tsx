"use client";

import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import {
  insightActivityQueryOptions,
  insightAggregatedQueryOptions,
  insightCountsQueryOptions,
  mergeInsightSeries
} from "@/features/admin/insights/insights";

const NUMBER = new Intl.NumberFormat("sv-SE");
const PRESET_DAYS = [7, 30, 90] as const;

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

function UsageChart({ days }: { days: number }) {
  const t = useTranslations();
  const locale = useLocale();

  const range = useMemo(() => {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);
    return { start: start.toISOString(), end: end.toISOString() };
  }, [days]);

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
  );
}

function ActivityCards({ days }: { days: number }) {
  const t = useTranslations();
  const range = useMemo(() => {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);
    return { start: start.toISOString(), end: end.toISOString() };
  }, [days]);

  const { data } = useQuery(insightActivityQueryOptions(browserApi, range));
  if (!data) return null;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <Stat
        label={t("active_assistants")}
        value={`${NUMBER.format(data.active_assistant_count)} / ${NUMBER.format(
          data.total_trackable_assistants
        )}`}
      />
      <Stat label={t("active_users")} value={NUMBER.format(data.active_user_count)} />
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
  const [days, setDays] = useState(30);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("insights")} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label={t("assistants")} value={NUMBER.format(counts.assistants)} />
        <Stat label={t("sessions")} value={NUMBER.format(counts.sessions)} />
        <Stat label={t("questions")} value={NUMBER.format(counts.questions)} />
      </div>

      <Card className="flex flex-col gap-4 p-6">
        <div className="flex items-center justify-between gap-4">
          <div className="flex flex-col gap-0.5">
            <h2 className="font-semibold">{t("assistant_usage")}</h2>
            <p className="text-muted-foreground text-sm">{t("assistant_usage_description")}</p>
          </div>
          <Select value={String(days)} onValueChange={(value) => setDays(Number(value))}>
            <SelectTrigger size="sm" className="w-44" aria-label={t("timeframe")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PRESET_DAYS.map((preset) => (
                <SelectItem key={preset} value={String(preset)}>
                  {t(`last_${preset}_days`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <UsageChart days={days} />
      </Card>

      <div className="flex flex-col gap-3">
        <h2 className="font-semibold">{t("insights_assistant_activity")}</h2>
        <ActivityCards days={days} />
      </div>
    </div>
  );
}
