"use client";

import { ChevronRight, CircleAlert, CircleCheck, LoaderCircle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { currentStep, type Activity } from "./activity";
import { ACTIVITY_PANEL_ID } from "./activity-panel";
import { stepTitle } from "./activity-steps";
import type { TurnDurations } from "./activity-timings";
import { formatSeconds } from "./format";

/**
 * Disclosure button summarising an answer's activity ("5 steg · 14,6 s · 22
 * källor"); while streaming it names the running step. It opens the Aktivitet
 * panel (aria-expanded/aria-controls).
 */
export function ActivityPill({
  activity,
  durations,
  expanded,
  onToggle
}: {
  activity: Activity;
  durations: TurnDurations | null;
  expanded: boolean;
  onToggle: (trigger: HTMLButtonElement) => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const live = currentStep(activity);
  const stepCount = activity.steps.length;
  const label = live
    ? `${stepTitle(live, t)}…`
    : [
        stepCount > 0 ? t("chat_activity_steps", { count: stepCount }) : null,
        durations?.totalMs != null ? formatSeconds(durations.totalMs, locale) : null,
        activity.sources.length > 0
          ? t("chat_activity_sources", { count: activity.sources.length })
          : null,
        activity.errorCount > 0 ? t("chat_activity_errors", { count: activity.errorCount }) : null
      ]
        .filter(Boolean)
        .join(" · ");
  const Icon = live ? LoaderCircle : activity.errorCount > 0 ? CircleAlert : CircleCheck;

  return (
    <button
      type="button"
      aria-expanded={expanded}
      aria-controls={expanded ? ACTIVITY_PANEL_ID : undefined}
      onClick={(event) => onToggle(event.currentTarget)}
      className={cn(
        "focus-visible:outline-ring inline-flex min-h-[30px] max-w-full items-center gap-1.5 self-start rounded-full py-1 ps-2 pe-2.5 text-[12.5px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11",
        expanded || live
          ? "bg-ax-accent-muted text-ax-text-accent"
          : "bg-ax-muted text-ax-text-secondary hover:text-ax-text"
      )}
    >
      <Icon
        aria-hidden="true"
        className={cn(
          "size-[15px] shrink-0",
          live && "animate-spin",
          !live && !expanded && (activity.errorCount > 0 ? "text-ax-warning" : "text-ax-success")
        )}
      />
      <span className="sr-only">{t("chat_activity_label")}: </span>
      <span className="truncate">{label}</span>
      <ChevronRight aria-hidden="true" className="size-3.5 shrink-0" />
    </button>
  );
}
