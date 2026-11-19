import { Card } from "@astryxdesign/core/Card";
import type { UseQueryResult } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { lazy, Suspense, useId, type ReactNode } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { activityDays, type InsightActivity, type InsightSource } from "./insight-figures";
import type { InsightRange } from "./insights-range";
import { SourceLegend } from "./source-tag";

const ActivityChart = lazy(() =>
  import("./insights-activity-chart").then((module) => ({ default: module.ActivityChart }))
);
/** The chart's height (`ACTIVITY_CHART_HEIGHT`), for the skeleton. */
const ACTIVITY_SKELETON_HEIGHT = 240;

/**
 * "Aktivitet per dag": the period's conversations per day stacked by source
 * (`sources`, in the page's order), with the sources' colours named beside
 * the heading, and under the chart what the view adds (`children`). One card
 * for an assistant's or group chat's insights and the organisation's.
 */
export function ActivityCard({
  activity,
  range,
  sources,
  children
}: {
  activity: UseQueryResult<InsightActivity>;
  range: InsightRange;
  sources: readonly InsightSource[];
  children?: ReactNode;
}) {
  const t = useTranslations();
  const headingId = useId();
  // The days the chart draws. The legend goes with the bars, and is there
  // while they load, so the chart does not push it in.
  const days = activity.data ? activityDays(activity.data.days, range) : [];
  const hasLegend = activity.data ? days.some((day) => day.total > 0) : activity.isPending;
  return (
    <Card>
      <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <h2 id={headingId} className="text-base font-semibold">
            {t("insights_activity_heading")}
          </h2>
          {hasLegend ? <SourceLegend sources={sources} /> : null}
        </div>
        <QueryStateBoundary query={activity} rows={1} height={ACTIVITY_SKELETON_HEIGHT}>
          {() => (
            <Suspense fallback={<LoadingState rows={1} height={ACTIVITY_SKELETON_HEIGHT} />}>
              <ActivityChart key={`${range.start}|${range.end}`} days={days} sources={sources} />
            </Suspense>
          )}
        </QueryStateBoundary>
        {children}
      </section>
    </Card>
  );
}
