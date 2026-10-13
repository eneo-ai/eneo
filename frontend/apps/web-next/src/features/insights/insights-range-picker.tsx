"use client";

import { DateRangeInput, type DateRangePreset } from "@astryxdesign/core/DateRangeInput";
import { useTranslations } from "next-intl";
import { useMemo } from "react";
import {
  INSIGHT_PRESET_DAYS,
  insightRangeOfDays,
  isoDate,
  type InsightRange
} from "./insights-range";

const PRESET_KEY: Record<(typeof INSIGHT_PRESET_DAYS)[number], string> = {
  7: "audit_last_7_days",
  30: "audit_last_30_days",
  90: "audit_last_90_days"
};

/**
 * The period insights cover: Astryx DateRangeInput with the last 7, 30 and
 * 90 days as presets and a calendar for any other range up to today. A
 * period is always set (no clear button): the statistics need one.
 */
export function InsightsRangePicker({
  value,
  onChange
}: {
  value: InsightRange;
  onChange: (range: InsightRange) => void;
}) {
  const t = useTranslations();
  const presets = useMemo<DateRangePreset[]>(
    () =>
      INSIGHT_PRESET_DAYS.map((days) => ({
        label: t(PRESET_KEY[days]),
        getRange: () => insightRangeOfDays(days)
      })),
    [t]
  );

  return (
    <DateRangeInput
      label={t("insights_period_label")}
      description={t("choose_timeframe_for_insights")}
      placeholder={t("insights_period_placeholder")}
      value={value}
      onChange={(next) => {
        if (next) onChange({ start: next.start, end: next.end });
      }}
      presets={presets}
      max={isoDate(new Date())}
      hasClear={false}
      numberOfMonths={1}
      weekStartsOn="mon"
      width="100%"
    />
  );
}
