import { useFormatter, useTranslations } from "use-intl";
import { cn } from "@/lib/utils";
import type { PeriodChange as Change } from "./insight-figures";

/**
 * A figure's change against the previous period: "+12 %" for a count,
 * "−2 procentenheter" for a share, "oförändrat" when it held. The sign and
 * the words carry it; the colour (up green, down red) only repeats them, and
 * a screen reader hears what it is compared with. `compact` (a table cell)
 * leaves out the note that there is nothing to compare with.
 */
export function PeriodChange({
  change,
  unit,
  compact = false
}: {
  change: Change;
  unit: "percent" | "points";
  compact?: boolean;
}) {
  const t = useTranslations();
  const format = useFormatter();
  if (change.kind === "none") {
    return compact ? null : (
      <span className="text-ax-text-secondary text-sm">{t("insights_change_none")}</span>
    );
  }
  const text =
    change.kind === "same"
      ? t("insights_change_unchanged")
      : unit === "percent"
        ? format.number(change.value / 100, { style: "percent", signDisplay: "always" })
        : t("insights_change_points", {
            points: format.number(change.value, { signDisplay: "always" }),
            size: Math.abs(change.value)
          });
  return (
    <span
      className={cn(
        "text-sm font-medium tabular-nums",
        change.kind === "same"
          ? "text-ax-text-secondary"
          : change.value > 0
            ? "text-ax-success"
            : "text-ax-error"
      )}
    >
      {text}
      <span className="sr-only"> {t("insights_compared_to_previous")}</span>
    </span>
  );
}
