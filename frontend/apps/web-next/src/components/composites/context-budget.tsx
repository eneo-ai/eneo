"use client";

import { Tooltip } from "@astryxdesign/core/Tooltip";
import { TriangleAlert } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
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

/**
 * How much of the model's context window the assistant's static inputs (prompt,
 * attachments) consume — as a single honest line, not a near-empty bar. Below 1%
 * it shows only the token total; the meter and warning colours appear only as
 * usage approaches the model's limit, where the number is actually actionable.
 *
 * The line is a button whose only job is the per-input breakdown: an Astryx
 * Tooltip shows it on hover, keyboard focus and tap, and is the button's
 * description for screen readers.
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
  const format = useFormatter();
  const compact = (value: number) =>
    format.number(Math.round(value), { notation: "compact", maximumFractionDigits: 1 });
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
      <Tooltip content={breakdown} touchTrigger="tap">
        <button
          type="button"
          className={cn(
            "rounded-ax-inner focus-visible:outline-ring inline-flex min-h-6 w-fit items-center gap-1.5 text-xs tabular-nums focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11",
            tone
          )}
        >
          {percent >= DANGER_AT ? <TriangleAlert aria-hidden="true" className="size-3.5" /> : null}
          <span>
            {t("context_budget")}: {summary}
          </span>
        </button>
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
