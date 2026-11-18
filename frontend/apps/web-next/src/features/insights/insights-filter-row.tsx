import { Switch } from "@astryxdesign/core/Switch";
import { useTranslations } from "use-intl";
import type { ReactNode } from "react";
import type { InsightRange } from "./insights-range";
import { InsightsRangePicker } from "./insights-range-picker";

/**
 * The insights' period and "Jämför med föregående period", with a view's own
 * filters between them (`children`, the source on an assistant's insights).
 * The controls wrap among themselves and line up under the period field's
 * label; the switch sits on the controls' centre line, in its own row's
 * control height when the filters wrap.
 */
export function InsightsFilterRow({
  range,
  onRangeChange,
  compare,
  onCompareChange,
  children
}: {
  range: InsightRange;
  onRangeChange: (range: InsightRange) => void;
  compare: boolean;
  onCompareChange: (compare: boolean) => void;
  children?: ReactNode;
}) {
  const t = useTranslations();
  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-end gap-3">
      <div className="min-w-0 flex-1 basis-56 sm:max-w-80">
        <InsightsRangePicker value={range} onChange={onRangeChange} compact />
      </div>
      {children}
      {/* As tall as the controls beside it, with the switch on their centre line. */}
      <div className="flex min-h-(--size-element-md) items-center">
        <Switch label={t("insights_compare_previous")} value={compare} onChange={onCompareChange} />
      </div>
    </div>
  );
}
