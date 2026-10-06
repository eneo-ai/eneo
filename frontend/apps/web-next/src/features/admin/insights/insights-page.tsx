"use client";

import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { browserApi } from "@/lib/api/browser";
import {
  type InsightsRange,
  assistantActivityRows,
  insightActivityQueryOptions,
  insightAggregatedQueryOptions,
  insightCountsQueryOptions,
  insightMetadataQueryOptions,
  isoFromDateInput,
  localDate,
  tenantAssistantsQueryOptions
} from "@/features/admin/insights/insights";

const NUMBER = new Intl.NumberFormat("sv-SE");
const PRESET_DAYS = [7, 30, 90] as const;
const CHART_HEIGHT = 320;
const UsageAreaChart = dynamic(
  () => import("./usage-area-chart").then((module) => module.UsageAreaChart),
  {
    loading: () => <LoadingState rows={1} height={CHART_HEIGHT} />,
    ssr: false
  }
);

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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="flex flex-col gap-1 p-6">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="text-3xl font-semibold tabular-nums">{value}</span>
    </Card>
  );
}

function UsageChart({ range }: { range: InsightsRange }) {
  const query = useQuery(insightAggregatedQueryOptions(browserApi, range));
  return (
    <QueryStateBoundary query={query} rows={1} height={CHART_HEIGHT}>
      {(data) => <UsageAreaChart data={data} />}
    </QueryStateBoundary>
  );
}

function Delta({ current, prior }: { current: number; prior?: number }) {
  if (prior == null) return null;
  const diff = current - prior;
  if (diff === 0) return <span className="text-muted-foreground text-xs">±0</span>;
  const up = diff > 0;
  return (
    <span className={up ? "text-success text-xs" : "text-destructive text-xs"}>
      {up ? "▲" : "▼"} {NUMBER.format(Math.abs(diff))}
    </span>
  );
}

function presetLabel(days: (typeof PRESET_DAYS)[number], t: (key: string) => string): string {
  switch (days) {
    case 7:
      return t("audit_last_7_days");
    case 30:
      return t("audit_last_30_days");
    case 90:
      return t("audit_last_90_days");
  }
}

function ActivityCards({ range, compare }: { range: InsightsRange; compare: boolean }) {
  const t = useTranslations();
  const { data, isPending } = useQuery(insightActivityQueryOptions(browserApi, range));
  const prior = useQuery({
    ...insightActivityQueryOptions(browserApi, priorRange(range)),
    enabled: compare
  });
  if (isPending) return <LoadingState rows={1} height={96} />;
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
                {NUMBER.format(row.questions)} {t("questions")} · {NUMBER.format(row.sessions)}{" "}
                {t("sessions")}
              </p>
            </div>
            <Button variant="outline" size="sm" asChild>
              <Link href={`/admin/insights/assistant/${row.assistantId}`}>
                <ExternalLink className="size-4" />
                {t("details")}
              </Link>
            </Button>
          </div>
        ))}
      </div>
    </Card>
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
  const [activePreset, setActivePreset] = useState<(typeof PRESET_DAYS)[number] | null>(30);
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
                  variant={activePreset === preset ? "default" : "outline"}
                  aria-pressed={activePreset === preset}
                  onClick={() => {
                    setActivePreset(preset);
                    setRange(presetRange(preset));
                  }}
                >
                  {presetLabel(preset, t)}
                </Button>
              ))}
            </div>
            <label className="flex flex-col gap-1 text-xs">
              {t("from")}
              <Input
                type="date"
                className="h-8 w-36"
                value={localDate(range.start)}
                onChange={(event) => {
                  if (!event.target.value) return;
                  setActivePreset(null);
                  setRange((current) => ({
                    ...current,
                    start: isoFromDateInput(event.target.value, "start")
                  }));
                }}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              {t("to")}
              <Input
                type="date"
                className="h-8 w-36"
                value={localDate(range.end)}
                onChange={(event) => {
                  if (!event.target.value) return;
                  setActivePreset(null);
                  setRange((current) => ({
                    ...current,
                    end: isoFromDateInput(event.target.value, "end")
                  }));
                }}
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
        <AssistantActivityList range={range} />
      </div>
    </div>
  );
}
