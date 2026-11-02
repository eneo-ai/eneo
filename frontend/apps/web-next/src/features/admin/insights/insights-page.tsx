import { useQuery } from "@tanstack/react-query";
import Link from "@/lib/link";
import { useFormatter, useTranslations } from "use-intl";
import { lazy, Suspense, useMemo, useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { Card } from "@astryxdesign/core/Card";
import { Button } from "@astryxdesign/core/Button";
import { Switch } from "@/components/astryx/switch";
import { InsightsRangePicker } from "@/features/insights/insights-range-picker";
import { insightRangeOfDays, type InsightRange } from "@/features/insights/insights-range";
import { tokenUsageQueryOptions } from "@/features/admin/usage/usage";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import {
  type InsightsRange,
  assistantActivityRows,
  insightActivityQueryOptions,
  insightAggregatedQueryOptions,
  insightMetadataQueryOptions,
  insightPeriod,
  previousInsightRange,
  periodTotals,
  insightTrend,
  tenantAssistantsQueryOptions
} from "@/features/admin/insights/insights";

const CHART_HEIGHT = 320;
const UsageAreaChart = lazy(() =>
  import("./usage-area-chart").then((module) => ({ default: module.UsageAreaChart }))
);

function Stat({
  label,
  value,
  children
}: {
  label: string;
  value: string;
  children?: React.ReactNode;
}) {
  return (
    <Card className="flex flex-row flex-wrap items-baseline justify-between gap-x-3 gap-y-1 p-4 sm:flex-col sm:items-start sm:justify-start sm:p-6">
      <span className="text-ax-text-secondary text-sm">{label}</span>
      <span className="text-2xl font-semibold tabular-nums sm:text-3xl">{value}</span>
      {children}
    </Card>
  );
}

function PercentageDelta({ current, previous }: { current: number; previous: number }) {
  const t = useTranslations();
  const format = useFormatter();
  const percent = insightTrend(current, previous);
  return (
    <span className="text-ax-text-secondary text-sm">
      {percent === null
        ? t("compare_new_activity_tooltip")
        : t("insights_period_change", {
            percent: format.number(percent / 100, { style: "percent", signDisplay: "exceptZero" })
          })}
    </span>
  );
}

function PeriodOverview({ range, compare }: { range: InsightRange; compare: boolean }) {
  const t = useTranslations();
  const format = useFormatter();
  const query = useQuery(insightAggregatedQueryOptions(browserApi, insightPeriod(range)));
  const previous = useQuery({
    ...insightAggregatedQueryOptions(browserApi, insightPeriod(previousInsightRange(range))),
    enabled: compare
  });
  return (
    <QueryStateBoundary query={query} rows={3} height={CHART_HEIGHT}>
      {(data) => {
        const totals = periodTotals(data);
        const prior = compare && previous.data ? periodTotals(previous.data) : null;
        return (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {(
                [
                  ["assistants", "assistants_created"],
                  ["sessions", "conversations_started"],
                  ["questions", "questions_asked"]
                ] as const
              ).map(([metric, label]) => (
                <Stat key={metric} label={t(label)} value={format.number(totals[metric])}>
                  {prior ? (
                    <PercentageDelta current={totals[metric]} previous={prior[metric]} />
                  ) : null}
                </Stat>
              ))}
            </div>
            {compare ? (
              <QueryStateBoundary query={previous} rows={1}>
                {() => null}
              </QueryStateBoundary>
            ) : null}
            <Card className="flex min-w-0 flex-col gap-4 p-4 sm:p-6">
              <h2 className="font-semibold">{t("assistant_usage")}</h2>
              <Suspense fallback={<LoadingState rows={1} height={CHART_HEIGHT} />}>
                <UsageAreaChart key={`${range.start}|${range.end}`} data={data} range={range} />
              </Suspense>
            </Card>
          </>
        );
      }}
    </QueryStateBoundary>
  );
}

function TokensCard({ range }: { range: InsightRange }) {
  const t = useTranslations();
  const format = useFormatter();
  const query = useQuery(
    tokenUsageQueryOptions(browserApi, {
      startTime: insightPeriod(range).start,
      endTime: insightPeriod(range).end
    })
  );
  return (
    <Card className="flex flex-col gap-3 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold">{t("tokens")}</h2>
        <Link
          className="text-ax-text-accent inline-flex min-h-6 items-center underline underline-offset-4 pointer-coarse:min-h-11"
          href={`/admin/usage?tab=tokens&from=${range.start}&to=${range.end}`}
        >
          {t("insights_token_usage_link")}
        </Link>
      </div>
      <QueryStateBoundary query={query} rows={1}>
        {(data) => (
          <dl className="grid gap-4 sm:grid-cols-3">
            {(
              [
                ["total_token_usage", "usage_total_tokens"],
                ["total_input_token_usage", "input_tokens"],
                ["total_output_token_usage", "output_tokens"]
              ] as const
            ).map(([key, label]) => (
              <div key={key}>
                <dt className="text-ax-text-secondary text-sm">{t(label)}</dt>
                <dd className="text-2xl font-semibold tabular-nums">{format.number(data[key])}</dd>
              </div>
            ))}
          </dl>
        )}
      </QueryStateBoundary>
    </Card>
  );
}

function Delta({ current, prior }: { current: number; prior?: number }) {
  const format = useFormatter();
  if (prior == null) return null;
  const diff = current - prior;
  if (diff === 0) return <span className="text-muted-foreground text-xs">±0</span>;
  const up = diff > 0;
  return (
    <span className={up ? "text-success text-xs" : "text-destructive text-xs"}>
      {up ? "▲" : "▼"} {format.number(Math.abs(diff))}
    </span>
  );
}

function ActivityCards({ range, compare }: { range: InsightRange; compare: boolean }) {
  const t = useTranslations();
  const format = useFormatter();
  const { data, isPending } = useQuery(
    insightActivityQueryOptions(browserApi, insightPeriod(range))
  );
  const prior = useQuery({
    ...insightActivityQueryOptions(browserApi, insightPeriod(previousInsightRange(range))),
    enabled: compare
  });
  if (isPending) return <LoadingState rows={1} height={96} />;
  if (!data) return null;
  const priorData = compare ? prior.data : undefined;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <Card className="flex flex-col gap-1 p-4 sm:p-6">
        <span className="text-muted-foreground text-sm">{t("active_assistants")}</span>
        <span className="flex items-baseline gap-2">
          <span className="text-3xl font-semibold tabular-nums">
            {format.number(data.active_assistant_count)} /{" "}
            {format.number(data.total_trackable_assistants)}
          </span>
          <Delta current={data.active_assistant_count} prior={priorData?.active_assistant_count} />
        </span>
      </Card>
      <Card className="flex flex-col gap-1 p-4 sm:p-6">
        <span className="text-muted-foreground text-sm">{t("active_users")}</span>
        <span className="flex items-baseline gap-2">
          <span className="text-3xl font-semibold tabular-nums">
            {format.number(data.active_user_count)}
          </span>
          <Delta current={data.active_user_count} prior={priorData?.active_user_count} />
        </span>
      </Card>
      <Stat label={t("total_assistants")} value={format.number(data.total_trackable_assistants)} />
    </div>
  );
}

function AssistantActivityList({ range }: { range: InsightsRange }) {
  const t = useTranslations();
  const metadata = useQuery(insightMetadataQueryOptions(browserApi, range));
  const assistants = useQuery(tenantAssistantsQueryOptions(browserApi));
  const rows = useMemo(
    () => (metadata.data ? assistantActivityRows(metadata.data) : []),
    [metadata.data]
  );
  const assistantNames = useMemo(
    () => new Map((assistants.data ?? []).map((assistant) => [assistant.id, assistant.name])),
    [assistants.data]
  );

  return (
    <QueryStateBoundary queries={[metadata, assistants]} rows={3} height={56}>
      {() =>
        rows.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("no_usage_data")}</p>
        ) : (
          <AssistantActivityRows rows={rows} assistantNames={assistantNames} />
        )
      }
    </QueryStateBoundary>
  );
}

function AssistantActivityRows({
  rows,
  assistantNames
}: {
  rows: ReturnType<typeof assistantActivityRows>;
  assistantNames: Map<string, string>;
}) {
  const t = useTranslations();
  return (
    <Card className="overflow-hidden p-0">
      <div className="divide-y">
        {rows.map((row) => (
          <div
            key={row.assistantId}
            className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
          >
            <div className="min-w-0">
              <p className="truncate font-medium">
                {assistantNames.get(row.assistantId) ?? row.assistantId}
              </p>
              <p className="text-muted-foreground text-sm">
                {t("insights_assistant_row_counts", {
                  questions: row.questions,
                  sessions: row.sessions
                })}
              </p>
            </div>
            <Button
              variant="secondary"
              size="sm"
              href={`/admin/insights/assistant/${row.assistantId}`}
              label={t("details")}
            />
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Organization activity over whole viewer-local days. */
export function InsightsPage() {
  const t = useTranslations();
  const { can } = useAppContext();
  const [range, setRange] = useState<InsightRange>(() => insightRangeOfDays(30));
  const [compare, setCompare] = useState(false);

  return (
    <div className="mx-auto flex w-full max-w-5xl min-w-0 flex-col gap-6">
      <PageHeader title={t("insights")} />
      <Card className="flex flex-wrap items-end gap-4 p-4 sm:p-6">
        <div className="min-w-0 flex-1">
          <InsightsRangePicker value={range} onChange={setRange} />
        </div>
        <Switch label={t("compare")} value={compare} onChange={setCompare} />
      </Card>
      <PeriodOverview range={range} compare={compare} />
      {can("admin") ? <TokensCard range={range} /> : null}
      <div className="flex flex-col gap-3">
        <h2 className="font-semibold">{t("insights_assistant_activity")}</h2>
        <ActivityCards range={range} compare={compare} />
        <AssistantActivityList range={insightPeriod(range)} />
      </div>
    </div>
  );
}
