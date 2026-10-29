"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { useTranslations } from "use-intl";
import { useMemo } from "react";
import { blockingError, ListError } from "@/components/composites/query-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { browserApi } from "@/lib/api/browser";
import { cn } from "@/lib/utils";
import { adminModelsQueryOptions, type ModelsPresentation } from "@/features/admin/models/models";
import {
  buildRateMap,
  defaultUsageRange,
  type UsageIntensity,
  type UsageRange
} from "@/features/admin/usage/usage";

export function percent(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 1
  }).format(Number.isFinite(value) ? value : 0);
}

export function share(part: number, total: number): number {
  return total > 0 ? part / total : 0;
}

/**
 * Model id → per-token cost, from the ratecard of the completion and embedding
 * models, and the ratecard's query: `CostNote` reports its failure.
 */
export function useCostRates() {
  const ratecard = useQuery(adminModelsQueryOptions(browserApi));
  const { data } = ratecard;
  const rates = useMemo(
    () => buildRateMap([...(data?.completion_models ?? []), ...(data?.embedding_models ?? [])]),
    [data]
  );
  return { rates, ratecard };
}

export type CostRates = ReturnType<typeof useCostRates>;

/**
 * Under a table with an estimated cost: what the estimate is (apps/web's tooltip
 * on each cost, said once), or, when the ratecard failed, why every cost is
 * "–" with a retry.
 */
export function CostNote({ ratecard }: { ratecard: UseQueryResult<ModelsPresentation> }) {
  const t = useTranslations();
  if (blockingError(ratecard)) {
    return (
      <ListError
        error={ratecard.error}
        title={t("usage_cost_rates_error")}
        isRetrying={ratecard.isFetching}
        onRetry={() => void ratecard.refetch()}
        compact
      />
    );
  }
  return <p className="text-muted-foreground text-xs">{t("estimated_cost_tooltip")}</p>;
}

export function DateRangeBar({
  range,
  onChange
}: {
  range: UsageRange;
  onChange: (range: UsageRange) => void;
}) {
  const t = useTranslations();
  return (
    <Card className="flex flex-wrap items-end gap-3 p-4">
      <label className="flex flex-col gap-1 text-xs">
        {t("from")}
        <Input
          type="date"
          className="h-8 w-36"
          value={range.from}
          max={range.to}
          onChange={(event) => {
            const from = event.target.value;
            if (from && from <= range.to) onChange({ ...range, from });
          }}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        {t("to")}
        <Input
          type="date"
          className="h-8 w-36"
          value={range.to}
          min={range.from}
          onChange={(event) => {
            const to = event.target.value;
            if (to && to >= range.from) onChange({ ...range, to });
          }}
        />
      </label>
      <Button variant="outline" size="sm" onClick={() => onChange(defaultUsageRange())}>
        <RotateCcw className="size-4" />
        {t("reset")}
      </Button>
    </Card>
  );
}

export const USAGE_LEVEL_CLASSES: Record<UsageIntensity, { badge: string; bar: string }> = {
  high: { badge: "border-destructive/40 text-destructive", bar: "bg-ax-error" },
  medium: { badge: "border-warning/40 text-warning", bar: "bg-ax-warning" },
  low: { badge: "border-success/40 text-success", bar: "bg-ax-success" }
};

export function UsageBadge({ level }: { level: UsageIntensity }) {
  const t = useTranslations();
  return (
    <Badge variant="outline" className={USAGE_LEVEL_CLASSES[level].badge}>
      {t(`usage_level_${level}`)}
    </Badge>
  );
}

export type UsageSegment = {
  key: string;
  /** The legend's name and figures for the segment: "Azure: 1,2 mn". */
  name: string;
  detail: string;
  value: number;
  /** Background class of the segment and its legend dot. */
  className: string;
};

/**
 * apps/web's overview bar: one stacked bar of the segments' shares of `total`
 * and a legend that names each one. The bar repeats the legend, so only the
 * legend is read out.
 */
export function UsageBar({ segments, total }: { segments: UsageSegment[]; total: number }) {
  return (
    <div className="flex flex-col gap-3">
      <div aria-hidden="true" className="bg-ax-muted flex h-4 w-full overflow-hidden rounded-full">
        {segments
          .filter((segment) => segment.value > 0)
          .map((segment) => (
            <div
              key={segment.key}
              className={cn("border-ax-card border-e-[3px] last:border-e-0", segment.className)}
              style={{ width: `${share(segment.value, total) * 100}%`, minWidth: "1.5%" }}
            />
          ))}
      </div>
      <ul className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        {segments.map((segment) => (
          <li key={segment.key} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className={cn(
                "border-ax-border-strong size-3 rounded-full border",
                segment.className
              )}
            />
            <span>
              <span className="font-medium">{segment.name}</span>: {segment.detail}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
