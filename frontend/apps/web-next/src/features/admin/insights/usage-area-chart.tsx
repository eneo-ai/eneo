"use client";

import { Button } from "@astryxdesign/core/Button";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { useFormatter, useLocale, useTranslations } from "use-intl";
import { useId, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import {
  groupedInsightSeries,
  insightDayCount,
  shiftInsightDate,
  type InsightGrouping,
  type MetadataStatisticsAggregated
} from "./insights";
import type { InsightRange } from "@/features/insights/insights-range";
import { formatCalendarDate } from "@/lib/calendar-date";

const WINDOW_DAYS = 45;
const WEEKDAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday"
] as const;

/** A bounded date window also keeps the chart's text alternative small for long periods. */
export function UsageAreaChart({
  data,
  range
}: {
  data: MetadataStatisticsAggregated;
  range: InsightRange;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const locale = useLocale();
  const descriptionId = useId();
  const [metric, setMetric] = useState<"sessions" | "questions">("sessions");
  const [grouping, setGrouping] = useState<InsightGrouping>("date");
  const maxOffset = Math.max(0, insightDayCount(range) - WINDOW_DAYS);
  const [offset, setOffset] = useState(maxOffset);
  const safeOffset = Math.min(offset, maxOffset);
  const rows = useMemo(() => groupedInsightSeries(data, grouping), [data, grouping]);
  const dateRows = useMemo(() => groupedInsightSeries(data, "date"), [data]);
  const firstActivity = dateRows.find((row) => row.sessions > 0 || row.questions > 0)?.date;
  const hasActivity = data[metric].some((point) => point.count > 0);
  const firstDate = shiftInsightDate(range.start, safeOffset);
  const visible =
    grouping === "date"
      ? Array.from(
          { length: Math.min(WINDOW_DAYS, insightDayCount(range) - safeOffset) },
          (_, index) => {
            const date = shiftInsightDate(firstDate, index);
            return (
              dateRows.find((row) => row.date === date) ?? {
                date,
                assistants: 0,
                sessions: 0,
                questions: 0
              }
            );
          }
        )
      : rows;
  const metricLabel = t(metric === "sessions" ? "new_conversations" : "new_questions");
  const groupingLabel = t(
    grouping === "date" ? "by_date" : grouping === "weekday" ? "by_weekday" : "by_hour"
  );
  const formatBucket = (value: string) =>
    grouping === "date"
      ? formatCalendarDate(value, locale, { day: "numeric", month: "short", year: "numeric" })
      : grouping === "weekday"
        ? t(WEEKDAYS[Number(value)]!)
        : `${String(value).padStart(2, "0")}:00`;

  return (
    <figure aria-describedby={descriptionId} className="min-w-0">
      <p id={descriptionId} className="sr-only">
        {t("assistant_usage_description")}
      </p>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <SegmentedControl
          label={t("insights_chart_metric")}
          value={metric}
          onChange={(value) => setMetric(value === "questions" ? "questions" : "sessions")}
          size="sm"
        >
          <SegmentedControlItem value="sessions" label={t("new_conversations")} />
          <SegmentedControlItem value="questions" label={t("new_questions")} />
        </SegmentedControl>
        <SegmentedControl
          label={t("insights_chart_grouping")}
          value={grouping}
          onChange={(value) =>
            setGrouping(value === "hour" || value === "weekday" ? value : "date")
          }
          size="sm"
        >
          <SegmentedControlItem value="date" label={t("by_date")} />
          <SegmentedControlItem value="weekday" label={t("by_weekday")} />
          <SegmentedControlItem value="hour" label={t("by_hour")} />
        </SegmentedControl>
      </div>
      {!hasActivity ? (
        <div className="text-ax-text-secondary flex h-80 items-center justify-center text-sm">
          {t("no_activity_title")}
        </div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={320}>
            <AreaChart data={visible} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={formatBucket}
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
                labelFormatter={(label) => formatBucket(String(label))}
                formatter={(value) => [format.number(Number(value)), metricLabel]}
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-container)",
                  color: "var(--popover-foreground)"
                }}
              />
              <Area
                type="monotone"
                dataKey={metric}
                name={metricLabel}
                stroke="var(--chart-1)"
                fill="var(--chart-1)"
                fillOpacity={0.15}
                strokeWidth={2}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
          {grouping === "date" && maxOffset > 0 ? (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <Button
                size="sm"
                label={t("insights_earlier_days")}
                isDisabled={safeOffset === 0}
                onClick={() => setOffset(Math.max(0, safeOffset - WINDOW_DAYS))}
              />
              <span className="text-ax-text-secondary text-sm">
                {formatBucket(firstDate)} – {formatBucket(visible.at(-1)!.date)}
              </span>
              <Button
                size="sm"
                label={t("insights_later_days")}
                isDisabled={safeOffset === maxOffset}
                onClick={() => setOffset(Math.min(maxOffset, safeOffset + WINDOW_DAYS))}
              />
            </div>
          ) : null}
          {/* The clipping block contains the table's intrinsic width on narrow screens. */}
          <div className="sr-only">
            <table>
              <caption>{t("assistant_usage")}</caption>
              <thead>
                <tr>
                  <th scope="col">{groupingLabel}</th>
                  <th scope="col">{metricLabel}</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((point) => (
                  <tr key={point.date}>
                    <th scope="row">{formatBucket(point.date)}</th>
                    <td>{format.number(point[metric])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {firstActivity && firstActivity > range.start ? (
        <figcaption className="text-ax-text-secondary mt-3 text-sm">
          {t("insights_first_activity_in_period", {
            date: formatCalendarDate(firstActivity, locale, { dateStyle: "medium" })
          })}
        </figcaption>
      ) : null}
    </figure>
  );
}
