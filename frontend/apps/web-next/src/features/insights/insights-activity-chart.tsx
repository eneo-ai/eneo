import { Button } from "@astryxdesign/core/Button";
import { useFormatter, useLocale, useTranslations } from "use-intl";
import { useId, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatCalendarDate } from "@/lib/calendar-date";
import type { ActivityDay, InsightSource } from "./insight-figures";
import { SOURCE_STYLE } from "./source-tag";

export const ACTIVITY_CHART_HEIGHT = 240;

/** Days shown at once: a 90-day period fits; a longer one pages through. */
const WINDOW_DAYS = 92;

/**
 * "Aktivitet per dag": conversations per local day, stacked by source, with
 * a tooltip and the same figures as a table for screen readers (the card's
 * heading row names the colours). A period longer than 92 days is shown a
 * window at a time, so the table stays small too.
 */
export function ActivityChart({
  days,
  sources
}: {
  days: ActivityDay[];
  sources: readonly InsightSource[];
}) {
  const t = useTranslations();
  const format = useFormatter();
  const locale = useLocale();
  const descriptionId = useId();
  const maxOffset = Math.max(0, days.length - WINDOW_DAYS);
  const [offset, setOffset] = useState(maxOffset);
  const safeOffset = Math.min(offset, maxOffset);
  const visible = days.slice(safeOffset, safeOffset + WINDOW_DAYS);
  const hasActivity = days.some((day) => day.total > 0);
  const formatDay = (date: string, year = false) =>
    formatCalendarDate(date, locale, {
      day: "numeric",
      month: "short",
      ...(year ? { year: "numeric" } : {})
    });
  const label = (source: InsightSource) => t(SOURCE_STYLE[source].label);

  return (
    <figure aria-describedby={descriptionId} className="flex min-w-0 flex-col gap-3">
      <p id={descriptionId} className="sr-only">
        {t("insights_activity_description")}
      </p>
      {!hasActivity ? (
        <div
          className="text-ax-text-secondary flex items-center justify-center text-sm"
          style={{ height: ACTIVITY_CHART_HEIGHT }}
        >
          {t("no_activity_title")}
        </div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={ACTIVITY_CHART_HEIGHT}>
            <BarChart data={visible} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={(value) => formatDay(String(value))}
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
                cursor={{ fill: "var(--accent)" }}
                labelFormatter={(value) => formatDay(String(value), true)}
                formatter={(value, name) => [format.number(Number(value)), name]}
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-container)",
                  color: "var(--popover-foreground)"
                }}
              />
              {sources.map((source) => (
                <Bar
                  key={source}
                  dataKey={source}
                  name={label(source)}
                  stackId="sources"
                  fill={SOURCE_STYLE[source].fill}
                  // An edge in the card's colour parts the stacked segments.
                  stroke="var(--color-background-card)"
                  strokeWidth={1}
                  maxBarSize={32}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
          {maxOffset > 0 ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Button
                size="sm"
                label={t("insights_earlier_days")}
                isDisabled={safeOffset === 0}
                onClick={() => setOffset(Math.max(0, safeOffset - WINDOW_DAYS))}
              />
              <span className="text-ax-text-secondary text-sm">
                {t("insights_activity_window", {
                  start: formatDay(visible[0]!.date, true),
                  end: formatDay(visible.at(-1)!.date, true)
                })}
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
              <caption>{t("insights_activity_heading")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("insights_activity_day")}</th>
                  {sources.map((source) => (
                    <th key={source} scope="col">
                      {label(source)}
                    </th>
                  ))}
                  {sources.length > 1 ? <th scope="col">{t("total")}</th> : null}
                </tr>
              </thead>
              <tbody>
                {visible.map((day) => (
                  <tr key={day.date}>
                    <th scope="row">{formatDay(day.date, true)}</th>
                    {sources.map((source) => (
                      <td key={source}>{format.number(day[source])}</td>
                    ))}
                    {sources.length > 1 ? <td>{format.number(day.total)}</td> : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </figure>
  );
}
