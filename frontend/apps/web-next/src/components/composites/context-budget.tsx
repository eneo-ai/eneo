"use client";

import { TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const PERCENT = 100;
const WARN_AT = 75;
const DANGER_AT = 90;

export type ContextSegment = {
  /** Stable key + accessible label. */
  key: string;
  label: string;
  tokens: number;
  /** Tailwind background class for the meter segment (e.g. "bg-chart-1"). */
  className: string;
};

const compact = (value: number) =>
  new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(
    Math.round(value)
  );

/**
 * How much of the model's context window the assistant's static inputs (prompt,
 * attachments) consume — as a single honest line, not a near-empty bar. Below 1%
 * it shows only the token total; the meter and warning colours appear only as
 * usage approaches the model's limit, where the number is actually actionable.
 */
export function ContextBudget({
  segments,
  maxTokens,
  className
}: {
  segments: ContextSegment[];
  maxTokens: number | null;
  className?: string;
}) {
  const t = useTranslations();
  const used = segments.reduce((sum, segment) => sum + segment.tokens, 0);
  const percent = maxTokens ? (used / maxTokens) * PERCENT : 0;
  const showPercent = maxTokens != null && percent >= 1;
  const showMeter = maxTokens != null && percent >= WARN_AT;

  const tone =
    percent >= DANGER_AT
      ? "text-destructive"
      : percent >= WARN_AT
        ? "text-warning"
        : "text-muted-foreground";

  const summary = showPercent
    ? `~${compact(used)} / ${compact(maxTokens)} ${t("tokens")} · ${Math.round(percent)}%`
    : `~${compact(used)} ${t("tokens")}`;
  const breakdown = segments
    .map((segment) => `${segment.label} ${compact(segment.tokens)}`)
    .join(" · ");

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            tabIndex={0}
            className={cn(
              "inline-flex w-fit items-center gap-1.5 text-xs tabular-nums outline-none",
              tone
            )}
          >
            {percent >= DANGER_AT ? (
              <TriangleAlert aria-hidden="true" className="size-3.5" />
            ) : null}
            <span>
              {t("context_budget")}: {summary}
            </span>
          </span>
        </TooltipTrigger>
        <TooltipContent>{breakdown}</TooltipContent>
      </Tooltip>
      {showMeter ? (
        <div className="bg-muted flex h-1 w-28 overflow-hidden rounded-full" aria-hidden="true">
          {segments.map((segment) => (
            <div
              key={segment.key}
              className={segment.className}
              style={{ width: `${Math.min(PERCENT, (segment.tokens / maxTokens) * PERCENT)}%` }}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
