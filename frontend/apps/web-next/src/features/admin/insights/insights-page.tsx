"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import { Card } from "@/components/ui/card";
import { browserApi } from "@/lib/api/browser";
import { insightCountsQueryOptions } from "@/features/admin/insights/insights";

const NUMBER = new Intl.NumberFormat("sv-SE");

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="flex flex-col gap-1 p-6">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="text-3xl font-semibold tabular-nums">{value}</span>
    </Card>
  );
}

/**
 * Organization insights. Ships the headline counts; the time-series charts and
 * per-assistant analytics drill-down are deferred (no chart infra yet; OQ-5
 * treats charts as approximate). Tracked in the ledger.
 */
export function InsightsPage() {
  const t = useTranslations();
  const { data } = useSuspenseQuery(insightCountsQueryOptions(browserApi));

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("insights")} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label={t("assistants")} value={NUMBER.format(data.assistants)} />
        <Stat label={t("sessions")} value={NUMBER.format(data.sessions)} />
        <Stat label={t("questions")} value={NUMBER.format(data.questions)} />
      </div>
      <p className="text-muted-foreground border-border rounded-lg border border-dashed p-4 text-xs">
        {t("insights_charts_deferred")}
      </p>
    </div>
  );
}
