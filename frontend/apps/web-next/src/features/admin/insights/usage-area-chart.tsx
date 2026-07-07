"use client";

import { useLocale, useTranslations } from "next-intl";
import { useId, useMemo } from "react";
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
import {
  type MetadataStatisticsAggregated,
  mergeInsightSeries
} from "@/features/admin/insights/insights";

const NUMBER = new Intl.NumberFormat("sv-SE");

const SERIES = [
  { key: "sessions", color: "var(--chart-1)", labelKey: "conversations_started" },
  { key: "questions", color: "var(--chart-2)", labelKey: "questions_asked" },
  { key: "assistants", color: "var(--chart-3)", labelKey: "assistants_created" }
] as const;

export function UsageAreaChart({ data }: { data: MetadataStatisticsAggregated }) {
  const t = useTranslations();
  const locale = useLocale();
  const descriptionId = useId();
  const series = useMemo(() => mergeInsightSeries(data), [data]);

  const dateFmt = useMemo(
    () =>
      new Intl.DateTimeFormat(locale === "sv" ? "sv-SE" : "en-US", {
        day: "numeric",
        month: "short"
      }),
    [locale]
  );
  const formatDay = (value: string) => dateFmt.format(new Date(`${value}T00:00:00`));

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
