"use client";

import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

const PERCENT = 100;

export type ContextSegment = {
  /** Stable key + accessible label. */
  key: string;
  label: string;
  tokens: number;
  /** Tailwind background class for the bar + legend swatch (e.g. "bg-chart-1"). */
  className: string;
};

const compact = (value: number) =>
  new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(
    Math.round(value)
  );

/**
 * How much of the model's context window the assistant's static inputs (prompt,
 * attachments, …) consume. `maxTokens` is the model's token limit; pass null when
 * no model is selected and the bar collapses to a plain token total.
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
  const usedPercent = maxTokens ? Math.min(PERCENT, (used / maxTokens) * PERCENT) : null;
  const scale = maxTokens ?? Math.max(used, 1);

  return (
    <div className={cn("flex flex-col gap-2 rounded-lg border p-3", className)}>
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="text-muted-foreground">{t("context_budget")}</span>
        <span className="font-mono">
          {maxTokens ? `${compact(used)} / ${compact(maxTokens)}` : compact(used)}
          {usedPercent !== null ? (
            <span className="text-muted-foreground">{` · ${Math.round(usedPercent)}%`}</span>
          ) : null}
        </span>
      </div>
      <div className="bg-muted flex h-2 overflow-hidden rounded-full" aria-hidden="true">
        {segments.map((segment) => (
          <div
            key={segment.key}
            className={segment.className}
            style={{ width: `${Math.min(PERCENT, (segment.tokens / scale) * PERCENT)}%` }}
          />
        ))}
      </div>
      <ul className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {segments.map((segment) => (
          <li key={segment.key} className="flex items-center gap-1.5">
            <span className={cn("size-2 rounded-full", segment.className)} aria-hidden="true" />
            <span>{`${segment.label} ${compact(segment.tokens)}`}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
